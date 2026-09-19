# Dataset global de demostración

IDs/relaciones/valores deterministas. Solo las fechas de creación dependen de la ejecución inicial/reset; se conservan en upsert.

| Colección maestra | Conteo limpio |
|---|---:|
| Rol | 3 |
| Estado | 13 |
| Usuario | 44 |
| Cliente | 40 |
| Almacen | 3 |
| UsuarioAlmacen | 3 |
| Producto | 40 |
| Stock | 40 |
| Zona | 3 |
| ZonaTramo | 24 |
| Transporte | 1 |

Total: **214 documentos maestros**. Operativas vacías: Pedido, PedidoDetalle, PedidoProceso, Guia, Worker, Carga, CargaDetalle, CargaTarea, RefreshToken, fs.files y fs.chunks.

## Identidades y relaciones

- Roles: ROL-ADMIN, ROL-VENDEDOR, ROL-COMPRADOR; Nombre contiene exactamente el rol Java.
- Usuarios: USR-ADMIN-01; USR-VEN-01..03; USR-COM-001..040. Logins admin, vendedor01..03, comprador01..40.
- Clientes: CLI-0001..0040, uno por comprador. Almacenes: ALM-01..03.
- UsuarioAlmacen: UA-01..03, vendedor del mismo número, relación 1:1.
- Productos: SKU-00001..00040, `_id=SKU`, IdUsuario vendedor.
- Stock: STK-00001..00040; uno por producto, solo en el almacén de su vendedor.

| Productos | Vendedor | Almacén | Cantidad |
|---|---|---|---:|
| SKU-00001..00014 | vendedor01 / USR-VEN-01 | ALM-01 | 14 |
| SKU-00015..00027 | vendedor02 / USR-VEN-02 | ALM-02 | 13 |
| SKU-00028..00040 | vendedor03 / USR-VEN-03 | ALM-03 | 13 |

Precio del producto n = 10.00 + 0.50×n, desde 10.50 hasta 30.00, dos decimales. Peso = 0.25×(((n−1) mod 8)+1), ciclo de 0.25 a 2.00 kg. Se generan con Decimal y persisten en Decimal128, sin float.

## Últimas tres unidades

**SKU-00001 / ALM-01 / vendedor01**: CantidadStock=3, ReservaStock=0, total=3; precio 10.50, peso 0.25 kg. No existe otro Stock del SKU en otro almacén. Producto oficial para 40 compradores simultáneos, 40 solicitudes idénticas, 20 pedidos de carga compitiendo y tráfico mixto.

Resto de productos: cantidades 20,30,50 en ciclo empezando en SKU-00002; reservas iniciales cero. Upsert nunca repone cantidades ni borra reservas; reset restaura el fixture.

## Zonas, tarifas y transporte

Zona._id contiene exactamente LIMA_METROPOLITANA, LIMA_PROVINCIA o PROVINCIA, sin aliases. IdEstado=ACTIVO. ZonaTramo.IdZona referencia ese `_id`; IDs ZT-01-01..08, ZT-02-01..08, ZT-03-01..08.

| Desde kg (incluido) | Hasta kg (excluido) | Lima Metropolitana | Lima Provincia | Provincia |
|---:|---:|---:|---:|---:|
| 0.00 | 1.00 | 8.00 | 12.00 | 16.00 |
| 1.00 | 3.00 | 12.00 | 18.00 | 24.00 |
| 3.00 | 5.00 | 16.00 | 24.00 | 32.00 |
| 5.00 | 10.00 | 22.00 | 33.00 | 44.00 |
| 10.00 | 20.00 | 30.00 | 45.00 | 60.00 |
| 20.00 | 50.00 | 45.00 | 67.50 | 90.00 |
| 50.00 | 250.00 | 90.00 | 135.00 | 180.00 |
| 250.00 | 2500.00 | 180.00 | 270.00 | 360.00 |

Tarifas ficticias de demo; campos DesdeKg/HastaKg/Tarifa Decimal128. Cobertura continua [0,2500), sin solapamientos. El máximo conservador de pedidos del fixture es 20 líneas×50 unidades×2 kg=2000 kg; queda cubierto incluso aunque cada almacén seed tenga menos de 20 SKU. Los productos futuros con otros pesos necesitarán revisar cobertura.

Un transporte: `_id=TRANS-1`, Nombre=Transportista Simulado, IdEstado=ACTIVO. .NET requiere exactamente uno activo.

## Estados y auditoría

RECIBIDO, EN_PROCESO, DESPACHADO, COMPENSANDO, ANULADO, REQUIERE_REVISION, ACTIVO, PROCESANDO, PROCESADA, ERROR, ACEPTADA, RECHAZADA, DUPLICADA.

13 estados, `_id=Nombre=código`. No se añaden estados de cola/reserva ni catálogos decorativos: esos campos técnicos tienen su propia representación en los servicios. ERROR corresponde a la extensión real de Carga. Todas las entidades activables del fixture tienen IdEstado=ACTIVO; Estado no tiene un estado de actividad recursivo.

Todos los maestros incluyen UsuarioCreacion=seed, FechaCreacion BSON Date UTC, UsuarioModificacion/FechaModificacion null. Upsert solo inserta ausentes; conserva cambios operacionales y auditoría. Reset elimina maestros seed identificados por IDs y UsuarioCreacion=seed y los crea de nuevo.

## Uso para el generador Excel posterior

Clientes válidos CLI-0001..0040, almacenes ALM-01..03, SKU-00001..00040 y las tres zonas anteriores. SKU-00015 con ALM-01 es un negativo de pertenencia determinista; SKU-99999 y CLI-9999 no existen en el fixture. Cada bloque debe usar SKU del mismo vendedor/almacén. Las 40 identidades permiten el escenario de clientes distintos sin altas manuales.

Credenciales ficticias en [credentials.md](credentials.md). No se genera aquí el Excel oficial ni archivos en datos/.
