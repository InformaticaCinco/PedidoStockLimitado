"""Consultas focalizadas transcritas de los servicios, sin importarlos ni ejecutarlos."""
from decimal import Decimal
from common import ToolError
from seed.seed_data import ZONES, BOUNDARIES


def active_ids(db):
    return list({'ACTIVO', *(d['_id'] for d in db.Estado.find({'Nombre': 'ACTIVO'}))})


def dotnet_queries(db):
    active = active_ids(db)
    transports = list(db.Transporte.find({'IdEstado': {'$in': active}}).limit(2))
    if len(transports) != 1:
        raise ToolError('Consulta .NET: TRANSPORTE_AUSENTE_O_AMBIGUO')
    resolved = {}
    # Include boundaries and values on either side, including the fixture maximum.
    weights = sorted({Decimal('.25'), Decimal('2000'), Decimal('2499.99'), *BOUNDARIES[:-1],
                      *(x - Decimal('.01') for x in BOUNDARIES[1:])})
    for zone in ZONES:
        zones = list(db.Zona.find({'$or': [{'_id': zone}, {'Codigo': zone}], 'IdEstado': {'$in': active}}))
        if len(zones) != 1:
            raise ToolError('Consulta .NET: ZONA_AUSENTE_O_AMBIGUA')
        tariffs = list(db.ZonaTramo.find({'IdZona': zones[0]['_id'], 'IdEstado': {'$in': active}}))
        result = []
        for weight in weights:
            matches = [t for t in tariffs if t['DesdeKg'].to_decimal() <= weight < t['HastaKg'].to_decimal()
                       and t['Tarifa'].to_decimal() >= 0]
            if len(matches) != 1:
                raise ToolError(f'Consulta .NET: tramo ausente/ambiguo en {zone} para {weight} kg')
            result.append({'kg': str(weight), 'tramo': matches[0]['_id'], 'tarifa': str(matches[0]['Tarifa'])})
        resolved[zone] = result
    return {'ok': True, 'executedDotnet': False, 'transporte': transports[0]['_id'], 'zonas': resolved}


def cargas_row(db, warehouse='ALM-01', sku='SKU-00001', client_id='CLI-0001', zone='LIMA_METROPOLITANA'):
    active = active_ids(db)
    def is_active(doc):
        return doc is not None and doc.get('IdEstado') in active
    if not is_active(db.Almacen.find_one({'_id': warehouse})):
        return 'ALMACEN_NO_EXISTE_O_INACTIVO'
    product = db.Producto.find_one({'SKU': sku})
    if not is_active(product):
        return 'SKU_NO_EXISTE_O_INACTIVO'
    if db.UsuarioAlmacen.find_one({'IdUsuario': product['IdUsuario'], 'IdAlmacen': warehouse}) is None:
        return 'SKU_NO_PERTENECE_AL_ALMACEN'
    client = db.Cliente.find_one({'_id': client_id})
    if client is None:
        return 'CLIENTE_NO_EXISTE'
    user = db.Usuario.find_one({'_id': client['IdUsuario']})
    if not is_active(user):
        return 'CLIENTE_USUARIO_INACTIVO'
    if db.Rol.find_one({'_id': user['IdRol'], 'Nombre': 'COMPRADOR'}) is None:
        return 'CLIENTE_NO_ES_COMPRADOR'
    zones = [z for z in db.Zona.find({'$or': [{'_id': zone}, {'Codigo': zone}]}) if is_active(z)]
    return 'OK' if len(zones) == 1 else 'ZONA_NO_EXISTE_O_INACTIVA'


def check_cargas(db):
    positive = cargas_row(db)
    negative = cargas_row(db, sku='SKU-00015')
    if positive != 'OK' or negative != 'SKU_NO_PERTENECE_AL_ALMACEN':
        raise ToolError('Compatibilidad cargas: resultado inesperado de pertenencia')
    return {'ok': True, 'executedCargas': False, 'positivo': positive, 'negativo': negative}
