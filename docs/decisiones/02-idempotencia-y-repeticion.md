# Decisión 02: idempotencia, repetición y recuperación

## Contexto

Un cliente puede reenviar una solicitud; un proceso puede morir después de un efecto externo y antes de registrar su resultado. Se necesita repetir trabajo sin duplicar pedidos, reservas ni guías, conservando evidencia de intentos. No se promete ejecución global exactamente una vez.

## Decisión

### Solicitudes y stock

`solicitudId` del contrato corresponde a `Pedido.IdSolicitud`, único globalmente. `HuellaContenido` representa la identidad del usuario comprador, almacén, zona y pares SKU/cantidad ordenados. Java construye una representación canónica y su hash SHA-256; no se publican aquí valores inventados. Misma solicitud y huella devuelve el pedido existente, mientras otra huella devuelve 409. En una carrera de altas el índice único decide el ganador y el perdedor vuelve a consultar/comparar.

Python resuelve cliente/usuario y construye una huella compatible; una solicitud repetida aparece DUPLICADA y una diferente con el mismo ID, RECHAZADA. `CargaDetalle(IdCarga, IndiceOriginal)` único evita recontar filas al recuperar una tarea.

`EstadoReserva` (NINGUNA, RESERVADA, LIBERADA, CONFIRMADA) gobierna los efectos de stock. Java retorna sin repetir cambios cuando la operación ya alcanzó su estado objetivo. Liberar NINGUNA no cambia existencias; otros estados incompatibles se rechazan. Repetir no equivale a permitir cualquier transición.

### Pasos y Worker .NET

`PedidoProceso` conserva `Paso`, `TipoProceso`, `IdEstadoProceso`, `NroIntento`, `FechaInicio`, `FechaFin` y `Log`. Java escribe aliases `STOCK_RESERVAR`, `STOCK_LIBERAR`, `STOCK_CONFIRMAR`; .NET los sincroniza a RESERVAR_STOCK, LIBERAR_STOCK y CONFIRMAR_DESPACHO, reutilizando el registro en lugar de duplicar el paso de stock.

`Worker` representa una corrida, con `FechaInicio`, `FechaFin`, `Intentos`, `LeaseOwner`, `LeaseVersion`, `LeaseHeartbeat`. Un índice único parcial limita las corridas abiertas del worker técnico. Una corrida vencida se reclama por actualización condicional: cambia propietario, incrementa LeaseVersion e Intentos. `Secuencia` se actualiza dentro de las transacciones de trabajo para que un propietario obsoleto no confirme escrituras después de perder el lease.

El heartbeat renueva cada `LeaseSeconds / 3` (10 segundos para los 30 de Compose); fallo o pérdida de lease cancela el trabajo local. El pedido conserva `IdWorker`, `FechaInicioProceso`, `FechaFinProceso`, `IntentoProceso`, `PasoPendiente`, `IntentosPasos` y otros indicadores de coordinación.

Al recuperar, se busca el pedido EN_PROCESO/COMPENSANDO incompleto de esa corrida. Se reevalúan reserva, envío y guía persistidos antes de continuar; después se cierra la corrida recuperada. No se reabre un DESPACHADO/ANULADO para simular reentrega. El endpoint ADMIN de reintento activa `ReintentoSolicitado` para un caso compatible en revisión; no salta las reglas del coordinador. Los intentos de corrida (`Intentos`), de proceso (`IntentoProceso`) y por paso (`NroIntento`/`IntentosPasos`) son conceptos distintos.

### Transportista, respuesta perdida y compensación

.NET envía la `Idempotency-Key` estable `despacho-guia-{pedidoId}` al POST `/guias`. Antes de generar consulta GET `/guias?pedidoId=...`; solo un 404 confirma ausencia. Escribe `GuiaIntentada` antes del efecto externo y vuelve a consultar cuando falla la generación. La guía local tiene unicidad por pedido. La anulación externa usa la clave estable `anulacion-despacho-guia-{pedidoId}`.

`PARTIAL_RATE` crea la guía y pierde la respuesta. La reconciliación recupera esa guía, sin crear otra con una clave nueva. La idempotencia externa depende del estado del simulador, que es volátil: no garantiza conservación tras reiniciar el transportista.

Ante anulación o timeout, se anula/reconcilia primero la guía y luego se libera stock reservado. Si no se puede verificar la compensación, se conserva REQUIERE_REVISION. Si stock ya fue confirmado, el coordinador registra `ANULACION_TRAS_CONFIRMACION_REQUIERE_AJUSTE_JAVA`: no declara una devolución inexistente. Una caída del transportista puede mantener reservas en revisión; no se liberan a ciegas ante un efecto remoto incierto.

### Cola de cargas

`CargaTarea` persiste EstadoTarea, Intentos, LeaseOwner, LeaseHasta y Secuencia. Python reclama/renueva tarea, verifica propiedad en transacciones, registra filas idempotentes y publica la referencia al reporte completo. GridFS y los metadatos de carga no constituyen un único commit atómico de archivo: existen mecanismos de limpieza y un posible pendiente operativo de huérfanos ante caída.

## Alternativas consideradas

Generar un nuevo ID en cada reintento permitiría duplicados. Confiar solo en HTTP 200/timeout no permite saber si ocurrió un efecto remoto. Locks en memoria no recuperan propiedad después de una caída. Una transacción distribuida que incluyera el transportista no está implementada ni es necesaria para este reto; se emplean efectos idempotentes, reconciliación y compensación persistida.

## Consecuencias

Se acepta repetición de intentos, pero se controla la repetición de efectos. Se necesita conservar las claves originales y estados técnicos. Hay consistencia eventual entre Mongo y el transportista; reintentos acotados pueden requerir decisión humana. Compartir colecciones y huella entre Java/Python exige mantener contratos compatibles. Lease/fencing no reemplazan la idempotencia externa.

## Evidencia

- [Reglas Java](../../services/pedidos-java/src/main/java/pe/reto/pedidos/domain/Reglas.java), [repositorio Java](../../services/pedidos-java/src/main/java/pe/reto/pedidos/adapter/out/mongo/MongoRepositorio.java).
- [.NET MongoRepositorio](../../services/despachos-dotnet/src/Despachos.Infrastructure/Mongo/MongoRepositorio.cs), [worker](../../services/despachos-dotnet/src/Despachos.Api/Workers/DespachoWorker.cs), [coordinador](../../services/despachos-dotnet/src/Despachos.Application/Coordinador.cs), [clientes HTTP](../../services/despachos-dotnet/src/Despachos.Infrastructure/Http/Clientes.cs).
- [Persistencia cargas](../../services/cargas-python/app/infrastructure/mongo.py), [worker cargas](../../services/cargas-python/app/application/worker.py).
- [E2E 02](../../tests/evidencias/e2e02-idempotencia-tres-envios.json), [03](../../tests/evidencias/e2e03-conflicto-solicitud.json) y [05](../../tests/evidencias/e2e05-repeticiones-02-10.json): repetición idéntica, conflicto y concurrencia por IdSolicitud.
- [E2E 08](../../tests/evidencias/e2e08-partial-rate-guia-unica.json), [11](../../tests/evidencias/e2e11-tarea-repetida.json), [12](../../tests/evidencias/e2e12-reinicio-despachos.json) y [13](../../tests/evidencias/e2e13-caida-mongodb.json): respuesta perdida, corrida vencida, SIGKILL y caída Mongo sin duplicar efectos finales.
- [E2E 09](../../tests/evidencias/e2e09-anulacion-durante-proceso.json), [10](../../tests/evidencias/e2e10-anulacion-estados-finales.json) y [14](../../tests/evidencias/e2e14-caida-transportista.json): compensación, estados terminales y revisión al agotar reintentos.

La evidencia acredita esos casos concretos; no demuestra ausencia de toda posible carrera ni alta disponibilidad productiva.
