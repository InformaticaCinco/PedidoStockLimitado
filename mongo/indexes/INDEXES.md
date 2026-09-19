# Inventario global de índices

Fuente: repositorios Mongo de Java, .NET y cargas-python inspeccionados. 25 índices funcionales, además de `_id_` automático por colección. Todos ascendentes.

| Colección | Claves (en orden) | Nombre | Opciones | Propietario | Razón |
|---|---|---|---|---|---|
| Pedido | IdSolicitud | `IdSolicitud_1` | `{"unique":true}` | Java/Python | Idempotencia global |
| Pedido | IdCliente, _id | `IdCliente_1__id_1` | `{}` | Java | Listado comprador |
| Producto | SKU | `SKU_1` | `{"unique":true}` | Java | SKU único |
| Producto | IdUsuario | `IdUsuario_1` | `{}` | Java | Pertenencia vendedor |
| Stock | IdAlmacen, IdProducto | `IdAlmacen_1_IdProducto_1` | `{"unique":true}` | Java | Stock único por almacén/producto |
| Usuario | Usuario | `Usuario_1` | `{"unique":true}` | Java | Login único |
| Cliente | IdUsuario | `IdUsuario_1` | `{"unique":true}` | Java | Un cliente por comprador |
| UsuarioAlmacen | IdUsuario | `IdUsuario_1` | `{"unique":true}` | Java | Un almacén por vendedor |
| UsuarioAlmacen | IdAlmacen | `IdAlmacen_1` | `{"unique":true}` | Java | Un vendedor por almacén |
| PedidoDetalle | IdPedido, IdProducto | `IdPedido_1_IdProducto_1` | `{"unique":true}` | Java/Python | Una línea por SKU |
| PedidoDetalle | IdUsuarioVendedor, IdPedido | `IdUsuarioVendedor_1_IdPedido_1` | `{}` | Java | Listado vendedor |
| PedidoProceso | IdPedido, FechaInicio | `IdPedido_1_FechaInicio_1` | `{}` | Java | Trazas cronológicas |
| Guia | IdPedido | `IdPedido_1` | `{"unique":true}` | Java/.NET | Una guía local por pedido |
| RefreshToken | Expiracion | `Expiracion_1` | `{"expireAfterSeconds":0}` | Java | Expiración de refresh |
| Worker | Nombre | `una_corrida_abierta` | `{"unique":true,"partialFilterExpression":{"FechaFin":null}}` | .NET | Una corrida abierta |
| Pedido | IdEstado, ReintentoSolicitado, FechaCreacion | `IdEstado_1_ReintentoSolicitado_1_FechaCreacion_1` | `{}` | .NET | Reclamo ordinario/reintento |
| Pedido | IdWorker, FechaFinProceso | `IdWorker_1_FechaFinProceso_1` | `{}` | .NET | Recuperación de corrida |
| PedidoProceso | IdPedido, Paso, NroIntento | `IdPedido_1_Paso_1_NroIntento_1` | `{}` | .NET | Historial de intentos |
| ZonaTramo | IdZona, IdEstado, DesdeKg, HastaKg | `IdZona_1_IdEstado_1_DesdeKg_1_HastaKg_1` | `{}` | .NET | Tarifas activas |
| CargaDetalle | IdCarga, IndiceOriginal | `IdCarga_1_IndiceOriginal_1` | `{"unique":true}` | Python | Una fila física; también sirve por IdCarga |
| CargaTarea | IdCarga | `IdCarga_1` | `{"unique":true}` | Python | Una tarea por carga |
| CargaTarea | EstadoTarea, ProximoIntento, LeaseHasta | `EstadoTarea_1_ProximoIntento_1_LeaseHasta_1` | `{}` | Python | Claim y recuperación |
| fs.files | metadata.cargaId, metadata.tipo | `metadata.cargaId_1_metadata.tipo_1` | `{}` | Python | Limpieza de reportes anteriores |
| fs.files | filename, uploadDate | `filename_1_uploadDate_1` | `{}` | GridFS | Índice estándar de versiones |
| fs.chunks | files_id, n | `files_id_1_n_1` | `{"unique":true}` | GridFS | Chunks únicos por archivo |

## Convergencia y conflictos

`python -m indexes.verify_indexes` inspecciona todo el inventario antes de crear lo faltante. `--check-only` no escribe y falla si falta alguno. Se comparan orden de claves, unique, sparse, hidden, TTL, partialFilterExpression y collation; metadatos de versión del servidor se ignoran.

Se aceptan índices con claves/opciones equivalentes aunque tengan otro nombre. Mismo nombre con otras claves u opciones, o mismas claves con opciones incompatibles: error explícito, código de salida 2. No se borran índices ni se eliminan duplicados para forzar creación. Índices adicionales no relacionados se conservan.

Los nombres creados desde cero coinciden con los que solicitan los servicios. Worker conserva el nombre explícito `una_corrida_abierta` y filtro `{FechaFin:null}`. RefreshToken conserva TTL=0. GridFS incluye sus dos índices estándar. No se agrega un índice de IdCarga redundante al prefijo de CargaDetalle.

Las pruebas reales verifican índices únicos, parcial de corrida abierta, TTL, conflictos de opciones y equivalencia de nombre. Ver `.build/indexes.json` y `.build/equivalent-index-name.json` para evidencia.

## Nombres alternativos y arranque de servicios

Comprobación real en MongoDB 7.0.16: un índice `SKU` unique llamado `sku_equivalente` es aceptado semánticamente por esta herramienta. Si después un servicio solicita las mismas claves/opciones con nombre `SKU_1`, Mongo devuelve **85 (IndexOptionsConflict)**. La evidencia es `.build/equivalent-index-name.json`.

No se borra/recrea el índice alternativo automáticamente: contradice la preservación solicitada y requiere tratar la base preexistente explícitamente. El seed desde cero crea siempre los nombres canónicos, y el JAR Java arrancó correctamente sobre ese inventario. Si se integra una base que ya usa nombres alternativos, coordinar la migración de nombres/arranque fuera de este paso; el listado `equivalent.actualName` permite detectarlos. No se modificaron los servicios para resolverlo.
