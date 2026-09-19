# Pedidos — despacho con stock limitado

Servicio en Java 21, Maven, Javalin 6, Dagger 2, driver oficial MongoDB 7, Nimbus RS256 y BCrypt. Puerto **8090**. Responsable de autenticación, catálogo, pedidos, pertenencia e integridad de stock. No contiene worker ni integración con el transportista.

## Arquitectura

`src/main/java/pe/reto/pedidos`: `domain` contiene modelos/reglas sin dependencias HTTP/Mongo/JWT; `application/port/in` expone pedidos, `application/port/out` define persistencia y seguridad; `application/usecase` aplica roles y coordina; `adapter/in/http` valida JSON y construye respuestas; `adapter/out/{mongo,security}` implementa los puertos. `config` construye el grafo Dagger con módulos Mongo, repositorios, seguridad, aplicación y HTTP; `bootstrap/Main` inicia índices y servidor. No hay Service Locator, Spring ni repositorios construidos por handlers. Las carpetas vacías del esqueleto original se conservan; el código está bajo el paquete Java indicado.

## Compilar y ejecutar

Desde **esta carpeta**, con `JAVA_HOME` apuntando a Java 21:

```bash
mvn clean test
mvn clean package
java -jar target/pedidos-1.0.0.jar
```

Maven descarga sus dependencias en `.build/m2` mediante `.mvn/maven.config`, sin escribir en otros proyectos. El JAR incorpora las dependencias; las claves se leen de las rutas configuradas, relativas al directorio de ejecución. El arranque requiere MongoDB disponible para crear/verificar índices. Después del arranque, `/health` no consulta dependencias.

Para probar integración real (Maven Failsafe):

```bash
MONGODB_TEST_URI='mongodb://localhost:27017/?replicaSet=rs0' mvn verify
# Alternativa: binario mongod 7 existente; la prueba levanta un replica set temporal:
MONGODB_TEST_BINARY='/ruta/absoluta/a/mongod' mvn verify
```

La suite crea bases aisladas `pedidos_it_<uuid>` y elimina únicamente esas bases al terminar. Con binario local, datos/logs van a `target/mongo-it-*` y el proceso se detiene al finalizar. Si no se configura URI ni binario, integración queda **omitida**, no aprobada. `mvn clean test` y `mvn clean package` ejecutan pruebas unitarias/HTTP; `mvn verify` ejecuta además integración. No se usa Docker ni `Thread.sleep` para sincronizar concurrencia.

## Configuración

`.env.example` contiene valores ficticios; la aplicación **no carga `.env` automáticamente**, deben exportarse las variables al proceso.

| Variable | Default |
|---|---|
| `PORT` | `8090` |
| `MONGODB_URI` | `mongodb://localhost:27017/?replicaSet=rs0` |
| `MONGODB_DATABASE` | `PedidoStockLimitado` |
| `JWT_ISSUER` | `http://localhost:8090` |
| `JWT_AUDIENCE` | `pedido-stock-limitado` |
| `JWT_ACCESS_EXP_SECONDS` | `900` |
| `JWT_REFRESH_EXP_SECONDS` | `604800` |
| `JWT_PRIVATE_KEY_PATH` | `keys/reto-private.pem` |
| `JWT_PUBLIC_KEY_PATH` | `keys/reto-public.pem` |
| `INTERNAL_API_KEY` | Vacío: rutas internas deshabilitadas. Mínimo 32 caracteres al configurar. |

## Endpoints

Todos los cuerpos de respuesta usan `{code,statusCode,message,data}`. Errores: `data:null` y `errores` cuando corresponda. Ver [CONTRATOS.md](CONTRATOS.md) para requests, responses y códigos.

| Método | Ruta | Acceso |
|---|---|---|
| GET | `/health` | Público |
| GET | `/health/dependencias` | Público |
| POST | `/auth/login` | Público, credenciales |
| POST | `/auth/refresh` | Refresh válido |
| POST | `/auth/logout` | Revoca refresh entregado |
| GET | `/.well-known/jwks.json` | Público |
| GET | `/productos` | COMPRADOR, VENDEDOR, ADMIN |
| POST | `/productos` | VENDEDOR |
| PUT | `/productos/{sku}` | VENDEDOR propietario |
| GET | `/productos/{sku}/stock?almacenId=ALM-01` | Roles autenticados |
| PUT | `/productos/{sku}/stock?almacenId=ALM-01` | VENDEDOR de producto y almacén |
| POST | `/pedidos` | COMPRADOR |
| GET | `/pedidos` | COMPRADOR propios, VENDEDOR líneas propias, ADMIN |
| GET | `/pedidos/{pedidoId}` | Pertenencia; ADMIN lectura global |
| POST | `/pedidos/{pedidoId}/anulacion` | COMPRADOR propietario o ADMIN |
| POST | `/internal/pedidos/{pedidoId}/stock/reservar` | Clave técnica interna |
| POST | `/internal/pedidos/{pedidoId}/stock/liberar` | Clave técnica interna |
| POST | `/internal/pedidos/{pedidoId}/stock/confirmar` | Clave técnica interna |

Las rutas de catálogo, edición, ajuste de stock y listados son **decisiones de contrato**, porque el requerimiento define su función pero no su URL. Listados: `?pagina=0`, base cero, 50 filas/pedidos por página. El vendedor recibe únicamente sus líneas y su subtotal/peso; no recibe identidad del comprador, solicitud, zona, guía, procesos ni importes globales. La única administración añadida es lectura global y solicitud de anulación; no se inventan APIs ADMIN ni cargas masivas.

## Autenticación y trazabilidad

`pedidos-java` es emisor. `RsaSeguridad` firma RS256 con claims `sub`, `rol`, `iss`, `aud`, `iat`, `exp`, `jti` y encabezado `kid`. Verifica algoritmo, firma, expiración, issuer, audience y `nbf` si existe. Identidad/auditoría vienen del JWT, nunca de body o `X-User-Id`. Comprador ajeno: 404; vendedor modificando producto/stock ajeno: 403. Campos JSON desconocidos se rechazan con 400, incluidos `clienteId`, precio de pedido o usuario de auditoría.

Login consulta `Usuario.IdRol -> Rol`; compara BCrypt y devuelve el mismo 401 para usuario inexistente y contraseña incorrecta. Longitud máxima de clave: 72 bytes UTF-8, límite de BCrypt. Refresh aleatorio de 256 bits; solo se persiste SHA-256. Rotación revoca el anterior e inserta el nuevo en **una transacción**. Logout revoca el refresh de forma idempotente; no revoca los access tokens ya emitidos, válidos hasta expirar.

`RefreshToken` es una **colección técnica de seguridad**, no reemplaza el modelo funcional. `_id` es el hash (índice único implícito), más `IdUsuario`, `Expiracion`, `Revocado`, `FechaRevocacion` y auditoría. TTL limpia expirados; la validez se comprueba explícitamente sin depender de la limpieza.

JWKS publica solo la clave pública, **en `data.keys`**, por la exigencia del sobre común para todas las respuestas. Los consumidores deben extraer `data` antes de cargar un JWKSet estándar; un lector JWKS automático sin adaptador no es compatible. Claves ficticias exclusivas del reto versionadas en `keys/`, incluida la privada por requerimiento.

Rutas internas: `X-Internal-Key`, comparación de tiempo constante; no aceptan un JWT de comprador/vendedor/ADMIN como sustituto. Auditoría técnica `SYSTEM:despachos`. Limitación deliberada: clave compartida sin identidad de servicio ni rotación automática; usar red interna/TLS al integrar. No hay credenciales reales.

Logs JSON con estado HTTP, tipo de error controlado y `correlationId` generado por servidor, devuelto en `X-Correlation-Id` y persistido al crear pedidos. No se registran cuerpos, rutas con datos personales, passwords, tokens, claves, nombres ni mensajes de excepciones de infraestructura. Los logs de bibliotecas HTTP/Mongo se deshabilitan para evitar filtraciones accidentales.

## MongoDB, stock e idempotencia

Colecciones usadas: `Rol`, `Usuario`, `Cliente`, `UsuarioAlmacen`, `Almacen`, `Producto`, `Stock`, `Pedido`, `PedidoDetalle`, `PedidoProceso`, `Guia` y la técnica `RefreshToken`. `Guia` solo se lee. Los estados se almacenan por código en `Pedido.IdEstado`; no se crea catálogo alternativo a `Estado`. No se usan todavía `Worker`, `Carga`, `CargaDetalle`, `Transporte`, `Zona` ni `ZonaTramo`.

Convención de identificadores: `_id` almacena el identificador conceptual; `Producto._id = SKU`, SKU globalmente único. Referencias `Stock.IdProducto` y `PedidoDetalle.IdProducto` usan ese valor. `UsuarioAlmacen` implementa relación uno a uno vendedor/almacén. `PedidoDetalle` guarda precio, peso y vendedor al registrar para conservar la pertenencia y los importes históricos.

Todas las escrituras creadas aquí llevan `UsuarioCreacion`, `FechaCreacion` BSON Date, `UsuarioModificacion:null`, `FechaModificacion:null`. Cada modificación completa los últimos dos campos. Dinero en `Decimal128`/`BigDecimal`, dos decimales `HALF_UP`. Peso en kg y decimal. El envío y total iniciales son `null`: el total definitivo requiere sumar el envío calculado posteriormente por despachos según `ZonaTramo`.

MongoDB 7 requiere **replica set**, de un nodo en desarrollo. Cliente y colecciones: lectura `MAJORITY`, escritura `MAJORITY`, preferencia `primary`. Transacciones: lectura `SNAPSHOT`, escritura `MAJORITY`, preferencia `primary`, sesiones causalmente consistentes. Las consultas compuestas del pedido también usan una transacción, para no combinar detalle/procesos de snapshots diferentes. El driver reintenta errores transitorios de transacción/commit según su protocolo. [Referencia oficial de transacciones](https://www.mongodb.com/docs/drivers/java/sync/current/crud/transactions/).

La creación de pedido y detalles es transaccional y **no reserva**. `IdSolicitud` único global protege la concurrencia. Huella SHA-256 incluye usuario autenticado, almacén, zona y líneas ordenadas por SKU; la validación precede a la huella (no normaliza entradas inválidas). Mismo contenido devuelve pedido/estado actual con 200; primera creación 202; distinto contenido o distinto comprador 409. Precio/peso se resuelven desde Producto; una repetición conserva los originales incluso si cambia el catálogo.

Reservar ordena líneas y ejecuta `findOneAndUpdate` con `CantidadStock >= q`: resta disponible y suma reservado. Una línea insuficiente aborta **toda** la transacción y deja un `PedidoProceso` fallido en otra transacción con motivo `STOCK_INSUFICIENTE`. Devuelve 409; despachos deberá decidir ANULADO. Liberar suma disponible y resta reserva con condición `ReservaStock >= q`; confirmar solo resta reserva. Repeticiones exitosas no vuelven a tocar stock ni duplican procesos. Confirmar después de liberar o liberar después de confirmar da 409. Liberar sin reserva es un no-op. Ajuste de vendedor fija solo **disponible**, conserva reservado y representa un cambio del stock real vigente.

Extensiones técnicas explícitas en `Pedido`:

- `HuellaContenido`, `CorrelationId`, `IdUsuarioComprador` (identidad histórica ligada a Cliente).
- `EstadoReserva`: `NINGUNA`, `RESERVADA`, `LIBERADA`, `CONFIRMADA`; marcador técnico, **no** nuevos estados funcionales. Se actualiza en la misma transacción que Stock para garantizar idempotencia.
- `AnulacionSolicitada` y `FechaSolicitudAnulacion`: solicitud persistente/idempotente para el coordinador, sin ejecutar compensación en Java.

La reserva pasa RECIBIDO a EN_PROCESO con transición validada. Confirmación/liberación no asignan DESPACHADO/ANULADO: despachos completará esas transiciones. La confirmación se rechaza si hay anulación pendiente; el coordinador debe resolver cualquier carrera con su confirmación final, guía y compensación. No hay estados nuevos. `PedidoProceso` guarda identificadores, tipo, paso, intento, inicio/fin Date, log y auditoría; `ms` se calcula al consultar y no se persiste.

### Índices programáticos

| Colección / índice | Motivo |
|---|---|
| Pedido `(IdSolicitud)` único | Idempotencia global concurrente |
| Pedido `(IdCliente, _id)` | Listado paginado del comprador |
| Producto `(SKU)` único | Identificación pública global |
| Producto `(IdUsuario)` | Productos por vendedor |
| Stock `(IdAlmacen, IdProducto)` único | Consulta/actualización exacta de stock |
| Usuario `(Usuario)` único | Login sin ambigüedad |
| Cliente `(IdUsuario)` único | Resolver comprador |
| UsuarioAlmacen `(IdUsuario)` y `(IdAlmacen)` únicos | Cardinalidad 1:1 y pertenencia |
| PedidoDetalle `(IdPedido, IdProducto)` único | Detalles sin duplicados |
| PedidoDetalle `(IdUsuarioVendedor, IdPedido)` | Listado del vendedor |
| PedidoProceso `(IdPedido, FechaInicio)` | Trazabilidad ordenada |
| Guia `(IdPedido)` único | Una guía por pedido |
| RefreshToken `(Expiracion)` TTL | Limpieza de tokens caducados |

Los identificadores `_id` usan los índices únicos nativos de MongoDB. El índice SKU, aunque el SKU también sea `_id`, respalda explícitamente el contrato y los filtros por el campo conceptual `SKU`; no se añade otro índice simple de producto. El `explain()` final queda para los datos globales del reto.

## Integraciones y pendientes

- **despachos-dotnet**: coordinar estados, leer solicitud de anulación, invocar operaciones internas, calcular envío, registrar guía/pasos, reintentar/compensar y recuperar worker. Acordar acceso a campos técnicos y validar transiciones con las reglas documentadas. No se implementó worker Java.
- **cargas-python**: cargas masivas respetando las mismas colecciones, Decimal128, auditoría y consistencia con reservas; validación JWT independiente.
- **Mongo global/Compose**: configurar replica set, servicio/red, secretos ficticios del reto, usuarios/roles/clientes/almacenes iniciales e índices compatibles. No se agregan usuarios de demostración al arranque: los fixtures existen solo en las pruebas.
- **frontend**: integrar contratos/sobre/JWT, catálogo, pedidos y anulación; autorización backend ya aplicada. CORS deberá definirse según el despliegue del host 8080 y remoto 8081.
- **JWKS de otros servicios**: extraer `data` y validar firma/exp/iss/aud de manera independiente. No hay rotación automática de claves RSA, plataforma de identidad de servicios ni revocación inmediata de access tokens.

Ningún archivo fuera de `services/pedidos-java` se modifica para este servicio.
