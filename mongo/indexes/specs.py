"""Inventario transcrito de los repositorios Java/.NET/Python, sin redefiniciones."""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Index:
    collection: str
    keys: tuple
    owner: str
    reason: str
    options: dict = field(default_factory=dict)

    @property
    def name(self):
        return self.options.get('name', '_'.join(f'{key}_{direction}' for key, direction in self.keys))


def spec(collection, fields, owner, reason, **options):
    return Index(collection, tuple((name, 1) for name in fields.split()), owner, reason, options)


INDEXES = [
    spec('Pedido', 'IdSolicitud', 'Java/Python', 'Idempotencia global', unique=True),
    spec('Pedido', 'IdCliente _id', 'Java', 'Listado comprador'),
    spec('Producto', 'SKU', 'Java', 'SKU único', unique=True),
    spec('Producto', 'IdUsuario', 'Java', 'Pertenencia vendedor'),
    spec('Stock', 'IdAlmacen IdProducto', 'Java', 'Stock único por almacén/producto', unique=True),
    spec('Usuario', 'Usuario', 'Java', 'Login único', unique=True),
    spec('Cliente', 'IdUsuario', 'Java', 'Un cliente por comprador', unique=True),
    spec('UsuarioAlmacen', 'IdUsuario', 'Java', 'Un almacén por vendedor', unique=True),
    spec('UsuarioAlmacen', 'IdAlmacen', 'Java', 'Un vendedor por almacén', unique=True),
    spec('PedidoDetalle', 'IdPedido IdProducto', 'Java/Python', 'Una línea por SKU', unique=True),
    spec('PedidoDetalle', 'IdUsuarioVendedor IdPedido', 'Java', 'Listado vendedor'),
    spec('PedidoProceso', 'IdPedido FechaInicio', 'Java', 'Trazas cronológicas'),
    spec('Guia', 'IdPedido', 'Java/.NET', 'Una guía local por pedido', unique=True),
    spec('RefreshToken', 'Expiracion', 'Java', 'Expiración de refresh', expireAfterSeconds=0),
    spec('Worker', 'Nombre', '.NET', 'Una corrida abierta', name='una_corrida_abierta', unique=True,
         partialFilterExpression={'FechaFin': None}),
    spec('Pedido', 'IdEstado ReintentoSolicitado FechaCreacion', '.NET', 'Reclamo ordinario/reintento'),
    spec('Pedido', 'IdWorker FechaFinProceso', '.NET', 'Recuperación de corrida'),
    spec('PedidoProceso', 'IdPedido Paso NroIntento', '.NET', 'Historial de intentos'),
    spec('ZonaTramo', 'IdZona IdEstado DesdeKg HastaKg', '.NET', 'Tarifas activas'),
    spec('CargaDetalle', 'IdCarga IndiceOriginal', 'Python', 'Una fila física; también sirve por IdCarga', unique=True),
    spec('CargaTarea', 'IdCarga', 'Python', 'Una tarea por carga', unique=True),
    spec('CargaTarea', 'EstadoTarea ProximoIntento LeaseHasta', 'Python', 'Claim y recuperación'),
    spec('fs.files', 'metadata.cargaId metadata.tipo', 'Python', 'Limpieza de reportes anteriores'),
    spec('fs.files', 'filename uploadDate', 'GridFS', 'Índice estándar de versiones'),
    spec('fs.chunks', 'files_id n', 'GridFS', 'Chunks únicos por archivo', unique=True),
]
