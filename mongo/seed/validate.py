import argparse
from datetime import datetime
from decimal import Decimal
import re

import bcrypt
from bson import Decimal128

from common import Settings, ToolError, cli, connect, database, require_replica
from indexes.verify_indexes import converge
from seed.seed_data import fixture, OPERATIONS, ROLES, ZONES, AUDIT_FIELDS, PASSWORD, BOUNDARIES
from seed.compatibility import dotnet_queries, check_cargas, active_ids


def need(condition, message):
    if not condition:
        raise ToolError('Invariante: ' + message)


def number(doc, key):
    need(isinstance(doc.get(key), Decimal128), f'{doc.get("_id")}.{key} debe ser Decimal128')
    value = doc[key].to_decimal()
    need(value.is_finite(), f'{doc["_id"]}.{key} debe ser finito')
    return value


def validate(db, *, initial=False):
    converge(db, create=False)
    expected = fixture()
    counts = {name: db[name].count_documents({}) for name in (*expected, *OPERATIONS)}
    warnings = []
    for collection, documents in expected.items():
        for wanted in documents:
            doc = db[collection].find_one({'_id': wanted['_id']})
            need(doc is not None, f'falta {collection}/{wanted["_id"]}')
            need(all(k in doc for k in AUDIT_FIELDS), f'auditoría incompleta {collection}/{doc["_id"]}')
            need(doc['UsuarioCreacion'] == 'seed' and isinstance(doc['FechaCreacion'], datetime), f'creación inválida {collection}/{doc["_id"]}')
            need((doc['UsuarioModificacion'] is None and doc['FechaModificacion'] is None) or
                 (isinstance(doc['UsuarioModificacion'], str) and isinstance(doc['FechaModificacion'], datetime)),
                 f'modificación inválida {collection}/{doc["_id"]}')
            if collection != 'Estado':
                need(doc.get('IdEstado') == 'ACTIVO', f'estado activo explícito requerido {collection}/{doc["_id"]}')
            differences = [key for key, value in wanted.items() if doc.get(key) != value]
            if initial:
                need(not differences, f'fixture inicial diferente {collection}/{doc["_id"]}: {differences}')
                need(doc['UsuarioModificacion'] is None, f'fixture inicial modificado {collection}/{doc["_id"]}')
            elif differences:
                warnings.append(f'{collection}/{doc["_id"]}: se conservan diferencias en {",".join(differences)}')
        if initial:
            need(counts[collection] == len(documents), f'conteo inicial {collection}')
    roles = {r['_id']: r['Nombre'] for r in db.Rol.find({})}
    need(len(roles) == 3 and set(roles.values()) == set(ROLES), 'roles = ADMIN, VENDEDOR, COMPRADOR')
    users = {u['_id']: u for u in db.Usuario.find({})}
    active = active_ids(db)
    is_active = lambda d: d is not None and d.get('IdEstado') in active
    verified_hashes = set()
    for user in users.values():
        need(user.get('IdRol') in roles, 'usuario con rol inexistente')
        need(not any(key.lower() in {'password', 'clave', 'contrasena', 'passwordplain'} for key in user), 'password plano en Usuario')
        encoded = user.get('ClaveHash')
        need(isinstance(encoded, str) and re.fullmatch(r'\$2a\$(?:0[4-9]|[12][0-9]|3[01])\$[./A-Za-z0-9]{53}', encoded), 'hash no compatible con jBCrypt')
        if encoded not in verified_hashes:
            try:
                demo_password = bcrypt.checkpw(PASSWORD.encode(), encoded.encode())
            except ValueError as exc:
                raise ToolError('Invariante: hash BCrypt inválido') from exc
            if initial:
                need(demo_password, 'credencial demo no válida')
            verified_hashes.add(encoded)
    by_role = {role: sum(roles[u['IdRol']] == role for u in users.values()) for role in ROLES}
    need(by_role['ADMIN'] >= 1 and by_role['VENDEDOR'] >= 3 and by_role['COMPRADOR'] >= 40, 'usuarios por rol')
    need(counts['Cliente'] >= 40 and counts['Producto'] >= 40 and counts['Almacen'] >= 3, 'conteos mínimos')
    for client in db.Cliente.find({}):
        buyer = users.get(client.get('IdUsuario'))
        need(is_active(buyer) and roles.get(buyer['IdRol']) == 'COMPRADOR', 'Cliente debe apuntar a COMPRADOR activo')
    for i in range(1, 4):
        user_id, warehouse = f'USR-VEN-{i:02d}', f'ALM-{i:02d}'
        relation = db.UsuarioAlmacen.find_one({'IdUsuario': user_id})
        need(relation is not None and relation['IdAlmacen'] == warehouse, 'relación vendedor/almacén seed')
        need(db.UsuarioAlmacen.count_documents({'IdUsuario': user_id}) == 1 and
             db.UsuarioAlmacen.count_documents({'IdAlmacen': warehouse}) == 1, 'relación 1:1')
    products = {p['_id']: p for p in db.Producto.find({})}
    for product in products.values():
        vendor = users.get(product.get('IdUsuario'))
        need(is_active(vendor) and roles.get(vendor['IdRol']) == 'VENDEDOR', 'Producto sin vendedor válido')
        relation = db.UsuarioAlmacen.find_one({'IdUsuario': vendor['_id']})
        need(relation is not None and is_active(db.Almacen.find_one({'_id': relation['IdAlmacen']})), 'Producto sin almacén activo')
        need(product.get('SKU') == product['_id'], 'Producto._id debe ser SKU')
        need(db.Stock.count_documents({'IdProducto': product['_id']}) == 1 and
             db.Stock.count_documents({'IdProducto': product['_id'], 'IdAlmacen': relation['IdAlmacen']}) == 1,
             'Producto requiere un Stock solo en almacén del vendedor')
        price, weight = number(product, 'Precio'), number(product, 'Peso')
        need(0 < price <= Decimal('999999999.99') and price.as_tuple().exponent == -2, 'precio positivo de dos decimales')
        need(0 < weight <= Decimal('100000') and weight.as_tuple().exponent >= -6, 'peso fuera de límites Java')
    for stock in db.Stock.find({}):
        need(stock.get('IdProducto') in products, 'Stock sin Producto')
        need(all(type(stock.get(key)) is int and 0 <= stock[key] <= 1000000000 for key in ('CantidadStock', 'ReservaStock')), 'stock entero no negativo')
    need(counts['Zona'] == 3, 'exactamente tres zonas')
    for zone in ZONES:
        need(is_active(db.Zona.find_one({'_id': zone})), 'zona activa')
        bands = list(db.ZonaTramo.find({'IdZona': zone, 'IdEstado': {'$in': active}}))
        for band in bands:
            need(number(band, 'DesdeKg') < number(band, 'HastaKg'), 'tramo vacío')
            rate = number(band, 'Tarifa')
            need(rate >= 0 and rate.as_tuple().exponent == -2, 'tarifa de dos decimales')
        bands.sort(key=lambda d: d['DesdeKg'].to_decimal())
        next_start = BOUNDARIES[0]
        for band in bands:
            need(band['DesdeKg'].to_decimal() == next_start, f'hueco/solapamiento en {zone}')
            next_start = band['HastaKg'].to_decimal()
        need(next_start == BOUNDARIES[-1], f'cobertura [0,2500) en {zone}')
    if initial:
        need(all(counts[c] == 0 for c in OPERATIONS), 'operaciones deben empezar vacías')
        need(all(s['ReservaStock'] == 0 for s in db.Stock.find({})), 'reserva inicial debe ser cero')
    stock = db.Stock.find_one({'IdProducto': 'SKU-00001', 'IdAlmacen': 'ALM-01'})
    special = {'disponible': stock['CantidadStock'], 'reservado': stock['ReservaStock'],
               'total': stock['CantidadStock'] + stock['ReservaStock']}
    if initial:
        need(special == {'disponible': 3, 'reservado': 0, 'total': 3}, 'últimas tres unidades')
    return {'ok': True, 'initial': initial, 'counts': counts, 'usersByRole': by_role, 'stockEspecial': special,
            'warnings': warnings, 'dotnetQueries': dotnet_queries(db), 'cargasQueries': check_cargas(db)}


def main():
    parser = argparse.ArgumentParser(description='Invariantes; --initial exige fixture exacto y operaciones vacías')
    parser.add_argument('--initial', action='store_true')
    args = parser.parse_args()
    settings = Settings.from_env()
    with connect(settings) as client:
        server = require_replica(client, settings)
        return validate(database(client, settings.database), initial=args.initial) | {'server': server}


if __name__ == '__main__':
    cli(main)
