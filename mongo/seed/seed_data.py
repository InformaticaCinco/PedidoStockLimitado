"""Fixture demo determinista; no datos personales ni secretos reales."""
from decimal import Decimal
from bson import Decimal128

PASSWORD = 'Reto2026!'
# Pre-generated once, $2a$ compatible with Java jBCrypt. Never re-salt on upsert.
PASSWORD_HASH = '$2a$10$XL9Qme/uJOPQlyC9z1cVg.mepA1wu2e2cAVGMXIK6SfIohfLprcyi'
ROLES = ('ADMIN', 'VENDEDOR', 'COMPRADOR')
STATES = ('RECIBIDO', 'EN_PROCESO', 'DESPACHADO', 'COMPENSANDO', 'ANULADO', 'REQUIERE_REVISION',
          'ACTIVO', 'PROCESANDO', 'PROCESADA', 'ERROR', 'ACEPTADA', 'RECHAZADA', 'DUPLICADA')
ZONES = ('LIMA_METROPOLITANA', 'LIMA_PROVINCIA', 'PROVINCIA')
BOUNDARIES = tuple(Decimal(v) for v in ('0.00', '1.00', '3.00', '5.00', '10.00', '20.00', '50.00', '250.00', '2500.00'))
BASE_RATES = tuple(Decimal(v) for v in ('8.00', '12.00', '16.00', '22.00', '30.00', '45.00', '90.00', '180.00'))
FACTORS = (Decimal('1.00'), Decimal('1.50'), Decimal('2.00'))
OPERATIONS = ('Pedido', 'PedidoDetalle', 'PedidoProceso', 'Guia', 'Worker', 'Carga', 'CargaDetalle',
              'CargaTarea', 'RefreshToken', 'fs.files', 'fs.chunks')
AUDIT_FIELDS = ('UsuarioCreacion', 'FechaCreacion', 'UsuarioModificacion', 'FechaModificacion')


def vendor_for(number):
    return 1 if number <= 14 else 2 if number <= 27 else 3


def active(identifier, **fields):
    return dict(_id=identifier, IdEstado='ACTIVO', **fields)


def fixture():
    data = {name: [] for name in ('Rol', 'Estado', 'Usuario', 'Cliente', 'Almacen', 'UsuarioAlmacen',
                                  'Producto', 'Stock', 'Zona', 'ZonaTramo', 'Transporte')}
    data['Rol'] = [active('ROL-' + role, Nombre=role) for role in ROLES]
    data['Estado'] = [dict(_id=state, Nombre=state) for state in STATES]
    data['Usuario'].append(active('USR-ADMIN-01', Usuario='admin', Nombre='Administrador Demo',
                                  IdRol='ROL-ADMIN', ClaveHash=PASSWORD_HASH))
    for number in range(1, 4):
        user = f'USR-VEN-{number:02d}'
        warehouse = f'ALM-{number:02d}'
        data['Usuario'].append(active(user, Usuario=f'vendedor{number:02d}', Nombre=f'Vendedor Demo {number:02d}',
                                     IdRol='ROL-VENDEDOR', ClaveHash=PASSWORD_HASH))
        data['Almacen'].append(active(warehouse, Nombre=f'Almacén Demo {number:02d}'))
        data['UsuarioAlmacen'].append(active(f'UA-{number:02d}', IdUsuario=user, IdAlmacen=warehouse))
    for number in range(1, 41):
        user = f'USR-COM-{number:03d}'
        data['Usuario'].append(active(user, Usuario=f'comprador{number:02d}', Nombre=f'Comprador Demo {number:02d}',
                                     IdRol='ROL-COMPRADOR', ClaveHash=PASSWORD_HASH))
        data['Cliente'].append(active(f'CLI-{number:04d}', IdUsuario=user))
        sku, vendor = f'SKU-{number:05d}', vendor_for(number)
        price = (Decimal('10.00') + Decimal(number) * Decimal('.50')).quantize(Decimal('.01'))
        weight = (Decimal((number - 1) % 8 + 1) * Decimal('.25')).quantize(Decimal('.01'))
        data['Producto'].append(active(sku, SKU=sku, IdUsuario=f'USR-VEN-{vendor:02d}', Nombre=f'Producto Demo {number:02d}',
                                      Precio=Decimal128(price), Peso=Decimal128(weight)))
        data['Stock'].append(active(f'STK-{number:05d}', IdAlmacen=f'ALM-{vendor:02d}', IdProducto=sku,
                                   CantidadStock=3 if number == 1 else (20, 30, 50)[(number - 2) % 3], ReservaStock=0))
    for number, (zone, factor) in enumerate(zip(ZONES, FACTORS), 1):
        data['Zona'].append(active(zone, Nombre=zone.replace('_', ' ').title()))
        for band, (low, high, base) in enumerate(zip(BOUNDARIES, BOUNDARIES[1:], BASE_RATES), 1):
            data['ZonaTramo'].append(active(f'ZT-{number:02d}-{band:02d}', IdZona=zone,
                DesdeKg=Decimal128(low), HastaKg=Decimal128(high),
                Tarifa=Decimal128((base * factor).quantize(Decimal('.01')))))
    data['Transporte'] = [active('TRANS-1', Nombre='Transportista Simulado')]
    return data
