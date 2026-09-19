# Contratos de cargas-python

## Sobre HTTP y autenticación

Respuesta JSON: `{"code":200,"statusCode":"HTTP_200_OK","message":"OK","data":{...}}`.
Error: `data:null`, mensaje seguro; `errores` cuando hay detalle de dependencias. Sin stack traces. Todas las rutas `/cargas` requieren `Authorization: Bearer <JWT RS256>` válido con rol ADMIN. Ausente/expirado/firma/issuer/audience/sub/claims inválidos: 401; rol distinto: 403. No hay login propio ni claves privadas en Python. JWKS Java envuelto: extraer `data.keys`, exigir sobre code=200 y claves RSA/RS256/sig con kid, sin parte privada. Caché 300 segundos; kid desconocido renueva.

X-Correlation-Id acepta `[A-Za-z0-9._:-]{1,100}`; inválido/ausente genera UUID. Se devuelve en todas las respuestas y se conserva en Carga/Pedido y logs; nunca decide identidad ni idempotencia. X-User-Id y X-Role no otorgan permisos.

| Endpoint | Entrada | Salida/códigos |
|---|---|---|
| GET /health | Pública | 200 `data:{estado:"UP"}` sin dependencias |
| GET /health/dependencias | Pública | 200 `data:{dependencias:[{nombre,estado,latenciaMs}]}`; MongoDB y JavaJWKS |
| POST /cargas | ADMIN; multipart, exactamente un archivo `archivo` | 202 `data:{cargaId:"CG-<uuid>"}` |
| GET /cargas/{id} | ADMIN | 200 estado/totales/reporte; 404 inexistente |
| GET /cargas/{id}/reporte | ADMIN | 200 binario XLSX; 409 no finalizado; 404 inexistente; 500 referencia/archivo inconsistente |

Dependencias caídas: 503 `data:null`, `errores:{dependencias:[...]}` con latencias y estados UP/DOWN. Excepciones inesperadas: 500 ERROR_INTERNO, sin detalle privado. No se usa 422.

## Recepción

Antes de 202: autenticación, parseo multipart en memoria, nombre sin rutas/caracteres de control y hasta 200 caracteres, extensión .xlsx sin distinguir mayúsculas, bytes no vacíos y tamaño ≤MAX_UPLOAD_BYTES. Otros campos, múltiples archivos, campo incorrecto, multipart incompleto o extensión/nombre inválidos: 400. Exceso: 413. El cuerpo total tiene un margen máximo de 16 KiB para framing multipart.

Se almacena GridFS ENTRADA; una transacción crea Carga PROCESANDO y CargaTarea PENDIENTE. Auditoría: sub del ADMIN y fecha BSON Date UTC; modificación inicialmente null. No se valida workbook ni se crea Pedido durante HTTP. Archivo corrupto/encabezados incorrectos se detectan en el worker; reintentos agotados producen ERROR, sin pedidos parciales.

Ejemplo GET durante o después del procesamiento:

```json
{"code":200,"statusCode":"HTTP_200_OK","message":"OK","data":{"cargaId":"CG-...","estado":"PROCESADA","totales":{"filas":3,"aceptadas":1,"rechazadas":1,"duplicadas":1},"reporte":"/cargas/CG-.../reporte"}}
```

PROCESANDO: reporte null, TotalFilas inicialmente 0 hasta parsear; resultados parciales solo desde filas ya persistidas. ERROR es estado técnico de Carga, separado de Pedido. PROCESADA requiere contadores coherentes y referencia al reporte. Estados de tarea: PENDIENTE, EN_PROCESO, COMPLETADA, FALLIDA.

## Excel y resultados

Columnas exactas, en cualquier orden: SOLICITUDID, CLIENTEID, ALMACENID, SKU, CANTIDAD, ZONAENTREGA, FECHASOLICITUD. Una hoja, encabezado fila 1, primera fila de datos índice 2. Columnas extra, repetidas o faltantes invalidan el workbook. Límite de seguridad 100000 filas y expansión ZIP de 20×MAX_UPLOAD_BYTES. No se exige 500 filas.

Los formatos y orden de validación están en README. Fecha Excel o texto exacto YYYY-MM-DDTHH:MM:SS; una cantidad decimal no entera, booleano o texto se rechaza. Excel puede almacenar 2.0 como entero 2; se valida el valor numérico leído, pues XLSX no conserva necesariamente esa distinción de escritura. No trim silencioso. Fórmulas se rechazan aunque exista valor cacheado.

Bloques consecutivos: mismo SOLICITUDID, 1–20 líneas sin SKU repetido y cliente/almacén/zona/fecha coherentes. Una fila inválida rechaza el bloque entero. Un ID rechazado puede aceptarse después. Misma IdSolicitud/huella Java: DUPLICADA con pedido existente; diferente: RECHAZADA sin alterar el original. Toda fila rechazada tiene IdPedido null. ACEPTADA implica Pedido real confirmado con todos sus detalles.

Motivos estables:

- CAMPO_VACIO:<columna>, ESPACIOS_NO_PERMITIDOS:<columna>, FORMATO_<columna>_INVALIDO.
- CANTIDAD_INVALIDA, FECHA_INVALIDA, ZONA_INVALIDA, FORMULA_NO_PERMITIDA.
- CANTIDAD_LINEAS_INVALIDA, SKU_REPETIDO_EN_SOLICITUD, SOLICITUD_INCONSISTENTE, SOLICITUD_INVALIDA.
- ALMACEN_NO_EXISTE_O_INACTIVO, SKU_NO_EXISTE_O_INACTIVO, SKU_NO_PERTENECE_AL_ALMACEN.
- CLIENTE_NO_EXISTE, CLIENTE_USUARIO_INACTIVO, CLIENTE_NO_ES_COMPRADOR, ZONA_NO_EXISTE_O_INACTIVA.
- OK, SOLICITUD_DUPLICADA, SOLICITUD_ID_CON_CONTENIDO_DISTINTO.

Reporte: Content-Type `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`; Content-Disposition `attachment; filename="reporte-CG-....xlsx"`. Columnas: INDICEORIGINAL, las siete originales, ESTADO, MOTIVO, IDPEDIDO. Se ordena por índice físico. Estados ACEPTADA/RECHAZADA/DUPLICADA. Texto en celdas OOXML inlineStr, incluso prefijos = + - @; no se generan elementos de fórmula. Fechas originales se representan en ISO si eran datetime Excel. Los enteros permanecen numéricos; otros escalares se representan como texto. Entrada/reporte operativos solo en memoria/GridFS.

## Mongo y compatibilidad física

| Conceptual | Campo físico adoptado |
|---|---|
| IdCarga / IdCargaDetalle / IdTarea | `_id`, prefijos CG-/CD-/CT- y UUID |
| IdPedido / IdPedidoDetalle | `_id`, PED-/DET- y UUID como Java |
| Estado inicial Pedido | IdEstado=RECIBIDO; EstadoReserva=NINGUNA |
| TotalPeso / CostoEnvio | PesoTotal / Envio |
| Zona de Pedido | ZonaEntrega código; CargaDetalle.IdZona resuelve `_id` real |
| Precio/peso de detalle | PrecioUnitario/PesoUnitario/Subtotal Decimal128 |
| Fecha funcional | CargaDetalle.FechaSolicitud; Java no tiene FechaPedido |

Carga conserva NombreArchivo, FechaCarga, TotalFilas, CantAceptadas, CantRechazadas, CantDuplicadas, IdEstadoProceso, Log, auditoría. Campos técnicos: ArchivoEntradaId/ArchivoReporteId y CorrelationId. CargaDetalle conserva campos solicitados + Original para el reporte, con valores inválidos sin normalizar. CargaTarea conserva campos de cola + Secuencia para fencing. Fechas técnicas UTC, modificaciones por cargas-python, creación ADMIN preservada.

Índices: Pedido.IdSolicitud único y PedidoDetalle(IdPedido,IdProducto) único, idénticos a Java. CargaDetalle(IdCarga,IndiceOriginal) único, también sirve por prefijo para agregación/orden. CargaTarea.IdCarga único y (EstadoTarea,ProximoIntento,LeaseHasta) para claim. GridFS: índices estándar filename/uploadDate y files_id/n únicos, más (metadata.cargaId,metadata.tipo) para limpiar reportes abandonados. No hay índice redundante de IdCarga en CargaDetalle.

ReadConcern majority, WriteConcern majority, Primary; transacciones Snapshot/Majority/Primary. Pedido, todos sus detalles y resultados de bloque son atómicos. La carrera duplicate key se resuelve releyendo al ganador en una nueva transacción. No se consulta Stock. No se introduce FechaPedido/IdZona alternativo en Pedido ni se asigna IdWorker.

Interpretación legado activa: ausencia de IdEstado en Producto/Usuario/Almacen se acepta porque Java ya los persiste así; estado explícito debe ser ACTIVO o apuntar a Estado.Nombre=ACTIVO. Zona requiere estado explícito. La disponibilidad de PDF y las ventanas de huérfanos GridFS están documentadas en README; no se ocultan como atomicidad inexistente de GridFS.
