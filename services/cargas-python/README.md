# Cargas masivas de pedidos

Servicio Python **3.12**, puerto **8092**. Recibe un XLSX de un ADMIN, conserva la entrada en GridFS y responde 202. Un worker toma tareas desde MongoDB 7, valida bloques consecutivos, crea pedidos compatibles con Java y publica un reporte XLSX. No consulta ni cambia Stock ni realiza despacho.

## Instalación y ejecución

Desde `services/cargas-python`:

```bash
python3.12 -m venv .venv
PIP_CACHE_DIR="$PWD/.build/pip-cache" .venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pip check
# Ajustar los valores del ejemplo a un MongoDB 7 replica set y al emisor Java.
set -a
source .env.example
set +a
.venv/bin/python -m app.main
```

`requirements.txt` fija dependencias directas y transitivas, incluidas las de pruebas. No hay Motor, Redis, Celery, SQL ni almacenamiento de archivos operativos en disco. La API usa FastAPI/Uvicorn, PyMongo Async y PyJWT/cryptography. openpyxl lee en un hilo; el reporte se escribe como OOXML dentro de un ZIP en memoria para evitar los temporales internos de `openpyxl.save()`.

| Variable | Predeterminado |
|---|---|
| PORT | 8092 |
| MONGODB_URI | mongodb://127.0.0.1:27017/?replicaSet=rs0 |
| MONGODB_DATABASE | pedido_stock_limitado |
| JWT_JWKS_URL | http://pedidos-java:8090/.well-known/jwks.json |
| JWT_ISSUER | http://localhost:8090 |
| JWT_AUDIENCE | pedido-stock-limitado |
| QUEUE_POLL_MS | 500 |
| QUEUE_LEASE_SECONDS | 30 |
| QUEUE_MAX_ATTEMPTS | 3 |
| QUEUE_RETRY_BASE_MS | 1000 |
| MAX_UPLOAD_BYTES | 10485760 |

Configurar **la misma base e issuer/audience que Java**; no asumir que todos los módulos tienen el mismo valor predeterminado. Las transacciones necesitan replica set. Los índices se crean al conectar el worker y antes de recibir una carga; `/health` no depende de Mongo ni del emisor.

## Uso

| Método/ruta | Acceso | Resultado |
|---|---|---|
| GET /health | Público | 200 liveness |
| GET /health/dependencias | Público | Mongo + JWKS Java, 200/503 |
| POST /cargas | ADMIN | Multipart `archivo`, 202 `{cargaId}` |
| GET /cargas/{id} | ADMIN | Estado, contadores de filas y enlace al reporte |
| GET /cargas/{id}/reporte | ADMIN | XLSX, o 409 mientras no esté PROCESADA |

```bash
curl -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H 'X-Correlation-Id: demo-carga-1' \
  -F 'archivo=@/ruta/entrada.xlsx' http://localhost:8092/cargas
```

El JWT se valida localmente con RS256, exp, iss, aud, sub y rol. Se extraen claves públicas desde **`data.keys`** del JWKS Java, con caché de cinco minutos y renovación por kid desconocido. La identidad de auditoría procede exclusivamente de `sub`.

## Excel, bloques e idempotencia

Una hoja, encabezado en fila 1, exactamente estas columnas (orden libre):
`SOLICITUDID CLIENTEID ALMACENID SKU CANTIDAD ZONAENTREGA FECHASOLICITUD`.

Solicitud: 1–60 alfanuméricos/guiones; cliente CLI-0000; almacén ALM-00; SKU-00000; cantidad entera 1–50; tres zonas oficiales; fecha Excel datetime o texto exacto YYYY-MM-DDTHH:MM:SS. No se recortan espacios ni se ejecutan fórmulas. Se conservan filas vacías internas/ocultas y sus índices físicos, empezando por 2. Límites técnicos: 100000 filas y tamaño ZIP expandido ≤20×MAX_UPLOAD_BYTES; no se exige que sean 500.

Negocio, en orden por fila: almacén activo → producto activo → Producto.IdUsuario/UsuarioAlmacen del mismo almacén → cliente/usuario COMPRADOR activo → Zona activa. No se usa Stock para pertenencia ni suficiencia.

Un bloque son filas **contiguas** con la misma solicitud. Debe tener 1–20 SKU distintos y cliente/almacén/zona/fecha coherentes. Si falla una fila, se rechaza todo el bloque sin Pedido; se continúa con el siguiente. El rechazo no consume la solicitud.

La huella reproduce Java: longitud UTF-16 del comprador, comprador, almacén, zona y líneas ordenadas SKU:cantidad; SHA-256 hexadecimal. Fecha, solicitudId y precios no integran esa huella porque Java tampoco los incluye. Misma solicitud/huella: DUPLICADA; contenido diferente: RECHAZADA. El índice global único IdSolicitud y la transacción resuelven carreras con Java u otras cargas.

Pedido + PedidoDetalle + CargaDetalle se confirman en una sola transacción Snapshot/Majority/Primary. El pedido nace RECIBIDO/NINGUNA, sin worker, con envío/total null y precios/pesos Decimal128 provenientes del catálogo. El comprador se resuelve desde CLIENTEID; el ADMIN queda en auditoría.

## Cola, GridFS y recuperación

`CargaTarea` reclama mediante findOneAndUpdate atómico; incrementa Intentos y asigna LeaseOwner/LeaseHasta. Un heartbeat renueva cada tercio del lease. Cada transacción verifica propietario, intento y vigencia y escribe la tarea para impedir commits de workers obsoletos. Reintentos: espera base×intento; al agotarse, FALLIDA/Carga ERROR. También se cierran leases vencidos en el último intento.

Una fila persistida no se reinterpreta al recuperar la tarea. Los contadores se agregan en Mongo, nunca se incrementan ciegamente. Al cerrar se exige filas=aceptadas+rechazadas+duplicadas. Una tarea completada que se reentrega conserva pedidos, resultados y reporte vigente.

Entrada y reporte van a GridFS con metadatos cargaId/tipo/nombreOriginal/fecha. El reporte tiene una fila por fila original, orden físico y texto literal protegido contra fórmula injection. Se descarga el reporte persistido; no se regenera en cada GET. Si un intento muere después de subir el reporte, el siguiente lo regenera y elimina las versiones anteriores tras publicar la referencia vigente.

GridFS no admite transacciones con los documentos funcionales. La entrada se sube antes de crear Carga/CargaTarea; una caída entre esos pasos puede dejar un archivo huérfano sin carga. Se conserva ante commit ambiguo para no borrar una entrada referenciada. Un uploader antiguo que termine muy tarde también puede dejar una versión no vigente. La referencia `Carga.ArchivoReporteId` define el único reporte funcional. La limpieza de huérfanos sin referencia requiere mantenimiento operacional; no afecta la unicidad de pedidos ni de filas.

Para demostrar recuperación, en una **base aislada** y con una tarea cuyo presupuesto no esté agotado:

```javascript
db.CargaTarea.updateOne(
  {IdCarga: "CG-REEMPLAZAR"},
  {$set: {EstadoTarea: "EN_PROCESO", LeaseHasta: new Date(0)}}
)
```

No resetear Intentos en producción para eludir su límite.

## Pruebas

```bash
.venv/bin/python -m pytest -q tests/test_domain.py tests/test_api.py
MONGODB_TEST_BINARY="$PWD/../pedidos-java/.build/mongo/mongodb-macos-aarch64-7.0.16/bin/mongod" \
  .venv/bin/python -m pytest -q tests/test_mongo.py tests/test_java.py
.venv/bin/python -m compileall -q app tests
```

Las integraciones levantan MongoDB **7 real**, replica set rsCargas, bases `cargas_it_<uuid>`, datos/logs en `.build`; eliminan las bases y detienen los procesos. La prueba Java requiere su JAR/claves existentes y el Java 21 local indicado en `tests/test_java.py`; no recompila ni escribe en ese módulo. Prueba login real, JWKS real, lectura de pedidos e idempotencia en ambas direcciones. No representa un despacho completo con .NET/transportista.

## Decisiones y pendientes externos

No estaban disponibles Requerimiento.pdf, ModelamientoDatos.pdf ni Diagrama.pdf en el proyecto/Descargas. Se adoptaron los campos conceptuales del prompt para Carga/CargaDetalle y los nombres físicos del código Java para Pedido. Java no persiste IdEstado en sus productos ni en algunos usuarios/almacenes: ausencia se interpreta como activo legado para esos tres catálogos; un estado explícito inactivo se rechaza. Zona exige estado activo explícito, como .NET. Se acepta ACTIVO o un IdEstado resuelto en Estado.Nombre=ACTIVO.

Java no soporta FechaPedido: la fecha funcional se conserva en CargaDetalle.FechaSolicitud, en UTC sin convertir la hora recibida; no se agrega un campo alternativo al pedido. Confirmar estas decisiones con los PDF cuando estén disponibles. Quedan fuera: archivo oficial, seed global, frontend, Compose, CI y despacho end-to-end. Resultados realmente ejecutados: [RESUMEN_FINAL.md](RESUMEN_FINAL.md); contrato detallado: [CONTRATOS.md](CONTRATOS.md).
