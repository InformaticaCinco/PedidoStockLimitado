# Despachos .NET

Servicio .NET 10/ASP.NET Core, puerto **8091**. Coordina pedidos, envío, guía, confirmación, reintentos, recuperación y compensación. MongoDB 7 es la única persistencia; **el stock se modifica exclusivamente mediante Java**. Usa DI nativa explícita, HttpClientFactory, BackgroundService y logs JSON.

## Ejecutar

Desde `services/despachos-dotnet`, con SDK .NET 10:

```bash
export DOTNET_CLI_HOME="$PWD/.build/dotnet"
export DOTNET_CLI_TELEMETRY_OPTOUT=1
export DOTNET_GENERATE_ASPNET_CERTIFICATE=false
export NUGET_HTTP_CACHE_PATH="$PWD/.build/nuget-http"
dotnet restore Despachos.slnx
dotnet build Despachos.slnx -c Release --no-restore
dotnet run --project src/Despachos.Api -c Release --no-build --no-launch-profile
```

Requiere MongoDB replica set, pedidos-java y transportista para completar pedidos. `/health` funciona sin dependencias; el worker espera/reintenta inicializar Mongo sin impedir liveness. No se cargan `.env` automáticamente: exportar los valores de `.env.example`. `Directory.Build.props` mantiene paquetes NuGet dentro de `.build/packages`. No se requiere Docker para compilar o ejecutar las pruebas aquí.

## Arquitectura

- `Despachos.Domain`: estados, modelos, cálculo decimal, reglas de transición; sin Mongo ni HTTP.
- `Despachos.Application`: puertos y `Coordinador`, sin implementación de stock.
- `Despachos.Infrastructure`: repositorio Mongo y clientes HTTP Java/transportista.
- `Despachos.Api`: DI, JWT/JWKS, endpoints, logs y BackgroundService.
- `tests/Despachos.Tests`: pruebas unitarias, HTTP controlado y pruebas reales opcionales.

## Configuración

| Variable | Default |
|---|---|
| `MONGODB_URI` | `mongodb://localhost:27017/?replicaSet=rs0` |
| `MONGODB_DATABASE` | `PedidoStockLimitado` |
| `PEDIDOS_BASE_URL` | `http://localhost:8090` |
| `PEDIDOS_INTERNAL_KEY` | Vacío; configurar igual a `INTERNAL_API_KEY` de Java |
| `TRANSPORTISTA_BASE_URL` | `http://localhost:9090` |
| `JWT_JWKS_URL` | Base Java + `/.well-known/jwks.json` |
| `JWT_ISSUER` | `http://localhost:8090` |
| `JWT_AUDIENCE` | `pedido-stock-limitado` |
| `WORKER_POLL_MS` | 1000 |
| `RETRY_MAX_ATTEMPTS` | 3, rango 1–20 |
| `RETRY_BASE_DELAY_MS` | 500; demora incremental por intento |
| `PROCESS_TIMEOUT_SECONDS` | 120 desde FechaInicioProceso |
| `HTTP_TIMEOUT_SECONDS` | 5 |
| `WORKER_LEASE_SECONDS` | 30; mínimo tres veces el timeout HTTP |

En Compose futuro: bases `http://pedidos-java:8090` y `http://transportista-simulator:9090`. Cambiar URLs de acceso no cambia automáticamente `JWT_ISSUER`; debe coincidir exactamente con el emisor Java.

## Contratos

Tres endpoints: `GET /health`, `GET /health/dependencias`, `POST /despachos/{pedidoId}/reintento` (ADMIN). [CONTRATOS.md](CONTRATOS.md) detalla cuerpos, códigos, JWT y contratos salientes. No se duplican login, catálogo ni anulación pública Java.

Se extrae **`data.keys` del JWKS Java** y se valida RS256/exp/iss/aud localmente mediante JwtBearer/IdentityModel. No se confía en headers de identidad. Configuración JWKS cacheada/renovada mediante ConfigurationManager; la clave privada no se lee ni se necesita en producción .NET.

## Adaptación al Mongo real de Java

El código Java es la fuente de verdad. No se crearon columnas duplicadas para los nombres conceptuales:

| Conceptual del prompt | Campo real utilizado |
|---|---|
| Pedido.IdPedido | Pedido._id |
| Pedido.IdEstadoProceso | Pedido.IdEstado (código oficial) |
| TotalPeso | PesoTotal |
| CostoEnvio | Envio |
| IdZona en Pedido | ZonaEntrega, resuelta contra Zona._id o Zona.Codigo |
| Peso de detalle | PedidoDetalle.PesoUnitario |
| SubTotal de detalle | PedidoDetalle.Subtotal |

Estados: RECIBIDO, EN_PROCESO, DESPACHADO, COMPENSANDO, ANULADO, REQUIERE_REVISION. No se añaden otros estados de pedido. El catálogo `Estado` se consulta para resolver ACTIVO en tarifas/zonas/transportes; los códigos de pedido siguen la representación ya utilizada por Java. Un estado activo admite el código `ACTIVO` o el `_id` de una fila Estado con `Nombre=ACTIVO`.

No existe seed de Zona/ZonaTramo/Transporte: se requiere una sola zona activa por código, exactamente un tramo aplicable y un transporte activo. Tramos **[DesdeKg, HastaKg)**; límite inferior inclusivo/superior exclusivo. Ausencia/ambigüedad se rechaza, sin tarifas ni transportistas inventados. Dinero/peso son `decimal`/Decimal128; redondeo AwayFromZero a dos decimales. Total = suma(Subtotal de detalle) + Envio.

## Worker, consistencia y recuperación

`Worker` representa una corrida. Un índice único parcial impide dos corridas abiertas para `Nombre=despachos-dotnet`. Solo se asigna `IdWorker` al reclamar atómicamente un pedido. Se persiste cada resultado antes de tomar el siguiente; se cierra con FechaFin.

Un proceso reiniciado recupera primero la corrida abierta cuyo lease haya vencido, retoma únicamente su pedido incompleto e incrementa solo su IntentoProceso. Conserva FechaInicioProceso para aplicar el timeout original, completa/compensa y cierra esa corrida. Los pedidos nunca tomados esperan una corrida nueva. Si el proceso sigue vivo, su heartbeat impide que otra instancia lo confunda con un reinicio.

Extensión técnica mínima en Worker: `LeaseOwner`, `LeaseVersion`, `LeaseHeartbeat`, `Secuencia`. Cada escritura coordinada verifica y escribe el lease dentro de la transacción (fencing) para rechazar propietarios antiguos. No se usa un lock en memoria como mecanismo de consistencia. La expiración de lease no es un nuevo campo FechaVencimiento del pedido. La seguridad de efectos HTTP sigue dependiendo de su idempotencia y de la clave estable, incluso ante pausas/reintentos.

Extensiones técnicas en Pedido: `PasoPendiente`, `FechaInicioPaso`, `IntentosPasos`, `GuiaIntentada`, `CompensacionPendiente`, `ReintentoSolicitado`, `FechaSolicitudReintento`, `CorrelationIdReintento`, además de los campos de worker/proceso del modelo. Java conserva la propiedad de `EstadoReserva` y los campos de solicitud de anulación.

Lecturas primary + MAJORITY, escrituras MAJORITY. Transacciones SNAPSHOT/MAJORITY para operaciones de múltiples documentos con fencing y cierres coherentes. No se mantiene una transacción abierta durante HTTP. Auditoría de creación preservada; modificaciones técnicas usan `despachos-dotnet`; ADMIN usa el `sub` validado.

Índices propios: corrida abierta única; Pedido `(IdEstado,ReintentoSolicitado,FechaCreacion)` e `(IdWorker,FechaFinProceso)`; PedidoProceso `(IdPedido,Paso,NroIntento)`; ZonaTramo `(IdZona,IdEstado,DesdeKg,HastaKg)`; Guia `IdPedido` único, compatible con el índice Java. No escribe Stock ni crea otras colecciones funcionales.

## Efectos, reintentos y compensación

Orden: RESERVAR_STOCK → CALCULAR_ENVIO → GENERAR_GUIA → CONFIRMAR_DESPACHO. Java recibe las tres rutas exactas `/internal/pedidos/{id}/stock/{reservar,liberar,confirmar}` y `X-Internal-Key`.

Los pasos Java `STOCK_RESERVAR`, `STOCK_LIBERAR`, `STOCK_CONFIRMAR` se actualizan en su registro original a los nombres del coordinador. Se preservan identificador/auditoría de creación; no se añade una fila redundante para la misma operación. Al recuperar también se normalizan registros Java que terminaron antes del corte. Duración derivable desde fechas, nunca se guarda `ms`.

Guía: se consulta antes de cualquier POST. Solo 404 confirma ausencia; 500/503/timeout/malformed nunca se interpretan como “no existe”. Antes de POST se persiste GuiaIntentada. Clave estable `despacho-guia-{pedidoId}`. Ante respuesta ambigua se consulta de nuevo; si se descubre guía se persiste y no se repite POST. Un índice único protege la relación local. El simulador deberá respetar idempotencia remota para garantizar una sola guía activa.

Los intentos por paso se conservan tras reiniciar. Espera incremental y máximo configurable; al agotarse, REQUIERE_REVISION con paso/observación/fechas, sin reintento automático. ADMIN habilita un nuevo ciclo de intentos conservando historial y efectos ya realizados. Stock insuficiente es terminal: ANULADO directamente, motivo `Stock insuficiente`, sin guía ni compensación. Tarifa ausente/ambigua compensa la reserva efectuada y anula.

Anulación/timeout: verificar antes, entre pasos y antes de confirmar. Compensar **ANULAR_GUIA → LIBERAR_STOCK**, solo para efectos reales o que deban reconciliarse. No liberar si la anulación de guía no fue confirmada. El cierre ANULADO verifica que no queda guía activa ni reserva; DESPACHADO requiere confirmación y ausencia de solicitud de anulación, mediante actualización condicional.

**Excepción acordada con el usuario:** si la anulación llega después de confirmar stock en Java pero antes del CAS DESPACHADO, pasar a REQUIERE_REVISION con `ANULACION_TRAS_CONFIRMACION_REQUIERE_AJUSTE_JAVA`. No declarar compensación completa ni restaurar stock directamente. Java actualmente rechaza liberar una reserva confirmada; cerrar esa carrera requiere cambiar el contrato Java en una tarea posterior.

## Correlación y logs

Aceptar/propagar `X-Correlation-Id`, generar si falta o es inválido y devolverlo en respuesta. El procesamiento usa el CorrelationId persistido del pedido. Logs JSON con servicio, pedido, worker, paso, intento, duración y resultado/error seguro; sin cuerpos, PII, passwords ni JWT.

**Pendiente Java:** su adaptador HTTP actualmente genera un correlationId nuevo aunque .NET envíe el header; .NET conserva y envía el original, pero la continuidad completa de logs Java requiere ajuste externo.

## Pruebas

```bash
# Unitarias y HTTP en memoria/handlers controlados:
dotnet test Despachos.slnx --filter 'Categoria!=MongoReal&Categoria!=JavaReal'
# MongoDB 7 real; datos aislados y servidor temporal si se proporciona binario:
MONGODB_TEST_BINARY=/ruta/a/mongod dotnet test Despachos.slnx --filter 'Categoria=MongoReal'
# Alternativamente MONGODB_TEST_URI a replica set real de pruebas.
```

Las pruebas Java real requieren adicionalmente `PEDIDOS_TEST_JAR`, `PEDIDOS_TEST_PRIVATE_KEY`, `PEDIDOS_TEST_PUBLIC_KEY`, `JAVA_TEST_BINARY`; leen artefactos existentes, sin modificar Java. El transportista es un servidor/handler controlado **solo en tests**. Los datos temporales y logs están bajo `.build`, las bases aisladas se eliminan y los procesos se detienen al terminar. Sin las variables de integración, esos tests se omiten explícitamente.

Ver [RESUMEN_FINAL.md](RESUMEN_FINAL.md) para comandos exactos, 46 resultados reales y pendientes. Fuentes técnicas: [JWT ASP.NET Core](https://learn.microsoft.com/en-us/aspnet/core/security/authentication/configure-jwt-bearer-authentication?view=aspnetcore-10.0), [transacciones driver MongoDB](https://www.mongodb.com/docs/drivers/csharp/current/crud/transactions/).
