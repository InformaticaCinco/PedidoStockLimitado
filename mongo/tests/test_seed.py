from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
import json

import bcrypt
from bson import Decimal128
from pymongo.errors import DuplicateKeyError, OperationFailure
import pytest

from common import Settings, ToolError
from indexes.specs import INDEXES
from indexes.verify_indexes import converge
from init.replica_set import initialize
from seed.seed import apply_seed
from seed.seed_data import fixture, OPERATIONS, PASSWORD, PASSWORD_HASH, ROLES, ZONES
from seed.validate import validate
from seed.compatibility import dotnet_queries, check_cargas
from tests.conftest import command, evidence, http


def test_initial_counts_roles(db):
    result = validate(db, initial=True)
    assert result['counts'] == {**{c: len(d) for c, d in fixture().items()}, **dict.fromkeys(OPERATIONS, 0)}
    assert {r['Nombre'] for r in db.Rol.find({})} == set(ROLES)
    assert result['usersByRole'] == {'ADMIN': 1, 'VENDEDOR': 3, 'COMPRADOR': 40}
    evidence('validation-initial.json', result)


def test_44_users_40_clients_bcrypt(db):
    users = list(db.Usuario.find({}))
    assert len(users) == 44 and db.Cliente.count_documents({}) == 40
    assert all(u['ClaveHash'] == PASSWORD_HASH and 'Clave' not in u for u in users)
    assert bcrypt.checkpw(PASSWORD.encode(), PASSWORD_HASH.encode())
    for n in range(1, 41):
        client = db.Cliente.find_one({'_id': f'CLI-{n:04d}'})
        user = db.Usuario.find_one({'_id': client['IdUsuario']})
        assert user['Usuario'] == f'comprador{n:02d}' and user['IdRol'] == 'ROL-COMPRADOR'


def test_vendors_products_stock_relations(db):
    for n, amount in [(1, 14), (2, 13), (3, 13)]:
        vendor, warehouse = f'USR-VEN-{n:02d}', f'ALM-{n:02d}'
        assert db.UsuarioAlmacen.count_documents({'IdUsuario': vendor, 'IdAlmacen': warehouse}) == 1
        products = list(db.Producto.find({'IdUsuario': vendor}))
        assert len(products) == amount
        for product in products:
            stock = db.Stock.find_one({'IdProducto': product['_id']})
            assert stock['IdAlmacen'] == warehouse and stock['ReservaStock'] == 0 and stock['CantidadStock'] >= 0
    assert db.Stock.count_documents({}) == 40
    stock = db.Stock.find_one({'IdProducto': 'SKU-00001'})
    assert (stock['CantidadStock'], stock['ReservaStock']) == (3, 0)


def test_active_audit_decimal(db):
    for collection, docs in fixture().items():
        for wanted in docs:
            doc = db[collection].find_one({'_id': wanted['_id']})
            if collection != 'Estado':
                assert doc['IdEstado'] == 'ACTIVO'
            assert doc['UsuarioCreacion'] == 'seed' and isinstance(doc['FechaCreacion'], datetime)
            assert doc['UsuarioModificacion'] is None and doc['FechaModificacion'] is None
    for p in db.Producto.find({}):
        assert isinstance(p['Precio'], Decimal128) and isinstance(p['Peso'], Decimal128)
        assert p['Precio'].to_decimal().as_tuple().exponent == -2
    for t in db.ZonaTramo.find({}):
        assert all(isinstance(t[k], Decimal128) for k in ('DesdeKg', 'HastaKg', 'Tarifa'))


def test_dotnet_queries_and_cargas_membership(db):
    net, cargas = dotnet_queries(db), check_cargas(db)
    assert set(net['zonas']) == set(ZONES) and net['transporte'] == 'TRANS-1'
    assert db.ZonaTramo.count_documents({}) == 24
    assert cargas['negativo'] == 'SKU_NO_PERTENECE_AL_ALMACEN'
    evidence('compatibility-queries.json', {'dotnet': net, 'cargas': cargas})


def test_second_seed_preserves_operations_stock_prices_password_and_audit(db):
    unchanged = {name: list(db[name].find({}).sort('_id')) for name in fixture()}
    apply_seed(db)
    assert {name: list(db[name].find({}).sort('_id')) for name in fixture()} == unchanged
    db.Pedido.insert_one({'_id': 'PED-EXTERNO', 'IdSolicitud': 'OPERACION-AJENA'})
    stamp = datetime.now(timezone.utc)
    db.Stock.update_one({'_id': 'STK-00001'}, {'$set': {'CantidadStock': 0, 'ReservaStock': 2,
        'UsuarioModificacion': 'despachos-dotnet', 'FechaModificacion': stamp}})
    db.Producto.update_one({'_id': 'SKU-00001'}, {'$set': {'Precio': Decimal128('99.99'),
        'UsuarioModificacion': 'USR-VEN-01', 'FechaModificacion': stamp}})
    changed_hash = bcrypt.hashpw(b'otra-demo', bcrypt.gensalt(rounds=4, prefix=b'2a')).decode()
    db.Usuario.update_one({'_id': 'USR-ADMIN-01'}, {'$set': {'ClaveHash': changed_hash,
        'UsuarioModificacion': 'admin', 'FechaModificacion': stamp}})
    before = {name: list(db[name].find({}).sort('_id')) for name in fixture()}
    result = apply_seed(db)
    assert not any(result['inserted'].values())
    assert {name: list(db[name].find({}).sort('_id')) for name in fixture()} == before
    assert db.Pedido.count_documents({'_id': 'PED-EXTERNO'}) == 1
    assert validate(db)['warnings']
    with pytest.raises(ToolError):
        validate(db, initial=True)
    evidence('preserved-operations.json', {'ok': True, 'pedidoPreservado': True, 'stockDisponible': 0,
        'stockReservado': 2, 'precio': '99.99', 'passwordOperativoPreservado': True, 'auditoriaPreservada': True})


def test_reset_known_scope_operations_empty_and_unknown_preserved(db):
    for name in OPERATIONS:
        db[name].insert_one({'_id': 'OP-' + name})
    db.ColeccionAjena.insert_one({'_id': 'NO-BORRAR'})
    db.Almacen.insert_one({'_id': 'ALM-99', 'Nombre': 'Ajeno', 'UsuarioCreacion': 'usuario'})
    db.Stock.update_one({'_id': 'STK-00001'}, {'$set': {'CantidadStock': 0, 'ReservaStock': 2}})
    result = apply_seed(db, reset=True)
    assert all(db[name].count_documents({}) == 0 for name in OPERATIONS)
    assert db.ColeccionAjena.find_one({'_id': 'NO-BORRAR'}) and db.Almacen.find_one({'_id': 'ALM-99'})
    assert db.Stock.find_one({'_id': 'STK-00001'})['CantidadStock'] == 3
    assert all(result['inserted'][name] == len(documents) for name, documents in fixture().items())


def test_safe_defaults_and_collision_rollback(empty_db):
    assert Settings().mode == 'upsert'
    for name in ('admin', 'local', 'config'):
        with pytest.raises(ToolError):
            Settings(database=name)
    with pytest.raises(ToolError):
        Settings(mode='RESET')
    empty_db.Producto.insert_one({'_id': 'SKU-00001', 'SKU': 'SKU-00001', 'UsuarioCreacion': 'ajeno'})
    empty_db.Pedido.insert_one({'_id': 'PED-AJENO', 'IdSolicitud': 'EXTERNO'})
    with pytest.raises(ToolError, match='maestro ajeno'):
        apply_seed(empty_db, reset=True)
    assert empty_db.Pedido.count_documents({}) == 1 and empty_db.Rol.count_documents({}) == 0


def test_replica_reinitialization_and_config_mismatch(mongo_settings):
    assert initialize(mongo_settings)['initialized'] is False
    with pytest.raises(ToolError, match='otra forma'):
        initialize(replace(mongo_settings, replica_set='otroRS'))


def test_indexes_inventory_and_real_constraints(db):
    result = converge(db)
    assert not result['created'] and len(result['equivalent']) == len(INDEXES) == 25
    with pytest.raises(DuplicateKeyError):
        db.Stock.insert_one({'_id': 'STK-OTHER', 'IdProducto': 'SKU-00001', 'IdAlmacen': 'ALM-01'})
    db.Worker.insert_one({'_id': 'W1', 'Nombre': 'despachos-dotnet', 'FechaFin': None})
    with pytest.raises(DuplicateKeyError):
        db.Worker.insert_one({'_id': 'W2', 'Nombre': 'despachos-dotnet', 'FechaFin': None})
    db.Worker.insert_one({'_id': 'W3', 'Nombre': 'despachos-dotnet', 'FechaFin': datetime.now(timezone.utc)})
    evidence('indexes.json', {'verification': result, 'indexes': {name: db[name].index_information() for name in db.list_collection_names()}})


def test_equivalent_index_different_name_is_accepted(db):
    db.Producto.drop_index('SKU_1')
    db.Producto.create_index('SKU', unique=True, name='sku_equivalente')
    result = converge(db)
    assert not result['created']
    assert any(i['actualName'] == 'sku_equivalente' for i in result['equivalent'])
    # Services request canonical names; record the real server response for a pre-existing alias.
    try:
        name = db.Producto.create_index('SKU', unique=True)
        outcome = {'canonicalCreateAccepted': True, 'returnedName': name}
    except OperationFailure as exc:
        assert exc.code == 85
        outcome = {'canonicalCreateAccepted': False, 'mongoCode': exc.code}
    evidence('equivalent-index-name.json', {'toolAcceptsEquivalent': True, **outcome})


@pytest.mark.parametrize('kind', ['unique', 'ttl', 'partial'])
def test_index_conflict_fails_without_destroying_data(db, kind):
    if kind == 'unique':
        db.Usuario.drop_index('Usuario_1')
        db.Usuario.create_index('Usuario')
    elif kind == 'ttl':
        db.RefreshToken.drop_index('Expiracion_1')
        db.RefreshToken.create_index('Expiracion', expireAfterSeconds=60)
    else:
        db.Worker.drop_index('una_corrida_abierta')
        db.Worker.create_index('Nombre', unique=True, name='una_corrida_abierta', partialFilterExpression={'FechaFin': {'$type': 'date'}})
    with pytest.raises(ToolError, match='incompatible'):
        apply_seed(db, reset=True)
    assert db.Usuario.count_documents({}) == 44


@pytest.mark.parametrize('kind', ['stock', 'active', 'decimal', 'overlap', 'gap', 'plaintext'])
def test_validator_detects_corruption(db, mongo_settings, kind):
    if kind == 'stock':
        db.Stock.update_one({'_id': 'STK-00001'}, {'$set': {'CantidadStock': -1}})
    elif kind == 'active':
        db.Producto.update_one({'_id': 'SKU-00001'}, {'$unset': {'IdEstado': ''}})
    elif kind == 'decimal':
        db.Producto.update_one({'_id': 'SKU-00001'}, {'$set': {'Precio': 10.5}})
    elif kind == 'overlap':
        db.ZonaTramo.update_one({'_id': 'ZT-01-02'}, {'$set': {'DesdeKg': Decimal128('.90')}})
    elif kind == 'gap':
        db.ZonaTramo.update_one({'_id': 'ZT-01-02'}, {'$set': {'DesdeKg': Decimal128('1.10')}})
    else:
        db.Usuario.update_one({'_id': 'USR-ADMIN-01'}, {'$set': {'Password': 'not-allowed'}})
    with pytest.raises(ToolError, match='Invariante'):
        validate(db)
    if kind == 'stock':
        result = command(mongo_settings, db.name, '-m', 'seed.validate')
        assert result.returncode == 2 and 'Invariante' in result.stderr


def test_real_cli_initial_second_reset_validation(empty_db, mongo_settings):
    cases = [('-m', 'init.replica_set'), ('-m', 'init.wait_for_primary'), ('-m', 'seed.seed'),
             ('-m', 'seed.seed'), ('-m', 'seed.seed', '--reset'), ('-m', 'seed.validate', '--initial'),
             ('-m', 'indexes.verify_indexes', '--check-only')]
    names = ['init-cli.json', 'primary-cli.json', 'seed-initial.json', 'seed-second.json',
             'seed-reset.json', 'validator-cli.json', 'indexes-cli.json']
    for args, name in zip(cases, names):
        result = command(mongo_settings, empty_db.name, *args)
        assert result.returncode == 0, result.stderr
        body = json.loads(result.stdout)
        assert body['ok']
        evidence(name, body)
    assert all(empty_db[c].count_documents({}) == 0 for c in OPERATIONS)
    assert empty_db.Stock.find_one({'_id': 'STK-00001'})['CantidadStock'] == 3


@pytest.mark.parametrize('login,role', [('admin', 'ADMIN'), ('vendedor01', 'VENDEDOR'), ('comprador01', 'COMPRADOR')])
def test_real_java_login(java, login, role):
    base, db = java
    status, body = http(base, '/auth/login', {'usuario': login, 'clave': PASSWORD})
    assert status == 200 and body['data']['usuario']['rol'] == role
    evidence(f'java-login-{role.lower()}.json', {'http': status, 'usuario': body['data']['usuario'], 'tokenOmitido': True})


def test_real_java_stock_three_units(java):
    base, db = java
    _, login = http(base, '/auth/login', {'usuario': 'comprador01', 'clave': PASSWORD})
    status, body = http(base, '/productos/SKU-00001/stock?almacenId=ALM-01', token=login['data']['accessToken'])
    assert status == 200
    assert {k: body['data'][k] for k in ('total', 'reservado', 'disponible')} == {'total': 3, 'reservado': 0, 'disponible': 3}
    evidence('java-stock.json', {'http': status, 'data': body['data']})
