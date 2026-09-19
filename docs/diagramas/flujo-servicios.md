# Flujo de servicios

Diagrama derivado de [docker-compose.yml](../../docker-compose.yml), [proxy del host](../../frontend/web-host/nginx.conf) y los adaptadores/coordinadores del código. Los puertos son los publicados al equipo anfitrión. El remoto es código que corre en el navegador; su contenedor entrega los assets, no ejecuta peticiones de negocio en el servidor.

```mermaid
flowchart TD
    U[Usuario / Navegador] --> H[web-host :8080 / Nginx]
    H -->|API /api/java| J[pedidos-java :8090]
    J -->|Pedidos, catálogo, auth, stock| M[(MongoDB :27017 / rs0)]
    H -->|Solo ADMIN: remoteEntry.js y Routes| R[admin-mfe :8081 / assets]
    R -.->|Se ejecuta dentro del host| A[ADMIN en navegador]
    A -->|Pedidos y anulación, proxy host| J
    A -->|Reintento, proxy host| D[despachos-dotnet :8091]
    A -->|Cargas y reporte, proxy host| C[cargas-python :8092]
    C -->|Carga, CargaTarea, GridFS, Pedido y detalles| M
    D -->|Worker, pedidos, pasos, tarifas y guía| M
    D -->|Reservar / confirmar / liberar stock| J
    D -->|Generar / consultar / anular guía| T[transportista-simulator :9090]
    D -.->|Obtener JWKS data.keys| J
    C -.->|Obtener JWKS data.keys| J
    I[mongo-init / tarea de arranque] -->|Replica set, índices y seed| M
```

Las flechas de ADMIN hacia APIs representan HTTP desde el navegador a los prefijos del Nginx del host. No hay llamadas directas ADMIN → transportista. Python no llama POST /pedidos de Java para importar: crea pedidos compatibles en Mongo; Java solo participa como proveedor JWKS para su autenticación. El simulador no persiste en Mongo.

## 1. Pedido normal y reserva

```mermaid
sequenceDiagram
    participant B as Navegador / host
    participant J as pedidos-java
    participant M as MongoDB
    participant D as Worker despachos-dotnet
    participant T as Transportista
    B->>J: POST /pedidos (JWT, solicitudId, almacén, líneas)
    J->>M: Transacción Pedido RECIBIDO y PedidoDetalle
    J-->>B: 202 nuevo / 200 repetido / 409 conflicto
    D->>M: Adquirir Worker y tomar pedido con lease
    D->>J: POST /internal/pedidos/id/stock/reservar
    J->>M: Transacción de todas las líneas y EstadoReserva
    J-->>D: RESERVADA o error de stock
    D->>M: Leer ZonaTramo y guardar envío/total
    D->>T: GET /guias?pedidoId=id
    alt Guía ausente (404)
        D->>M: Persistir GuiaIntentada antes del efecto
        D->>T: POST /guias + Idempotency-Key estable
        T-->>D: Guía o respuesta perdida
        opt Resultado incierto
            D->>T: GET /guias?pedidoId=id para reconciliar
            T-->>D: Guía existente o ausencia verificable
        end
    else Guía existente
        T-->>D: Guía para reutilizar
    end
    D->>M: Guardar guía local y pasos
    D->>J: POST /internal/pedidos/id/stock/confirmar
    J->>M: ReservaStock -= cantidad y CONFIRMADA, transacción
    J-->>D: Estado de reserva confirmado
    D->>M: Cierre condicional DESPACHADO sin anulación pendiente
    B->>J: GET /pedidos/id
    J-->>B: Estado, importes, guía y pasos
```

La reserva exige `CantidadStock >= cantidad` y mueve disponible a reservado. Confirmar reduce reservado sin volver a descontar disponible. El cálculo del envío lo realiza .NET con tarifas Mongo, no el transportista. El diagrama muestra el camino exitoso; si no hay stock, la transacción revierte todas las líneas y el coordinador puede terminar ANULADO sin generar guía.

## 2. Compensación

```mermaid
flowchart TD
    S[Anulación solicitada o timeout] --> Q{Stock CONFIRMADA?}
    Q -->|Sí| V[REQUIERE_REVISION: ajuste Java pendiente]
    Q -->|No| P[COMPENSANDO si hay efectos pendientes]
    P --> G{Guía local o GuiaIntentada?}
    G -->|Sí| A[ANULAR_GUIA: reconciliar si falta guía local y anular externa]
    A --> K{Resultado verificado?}
    K -->|No| V
    K -->|Sí| R{Reserva RESERVADA?}
    G -->|No| R
    R -->|Sí| L[LIBERAR_STOCK: llamada interna a Java]
    L --> F{Compensación verificada?}
    R -->|No| F
    F -->|Sí| N[ANULADO]
    F -->|No| V
```

Java registra la solicitud de anulación; .NET ejecuta los pasos. Se anula la guía antes de liberar stock. Un pedido ya DESPACHADO rechaza la solicitud con 409; repetirla sobre ANULADO es idempotente. La carrera posterior a CONFIRMADA no se presenta como compensación completada. Evidencias: [E2E 09](../../tests/evidencias/e2e09-anulacion-durante-proceso.json) y [10](../../tests/evidencias/e2e10-anulacion-estados-finales.json).

## 3. Recuperación de Worker

1. `Worker` mantiene una corrida abierta, propietario, versión y heartbeat. El proceso vivo renueva su lease; sin renovación, vence.
2. Otro ciclo de adquisición reclama condicionalmente esa misma corrida, incrementando `LeaseVersion` e `Intentos`. Las escrituras verifican el lease y actualizan `Secuencia` transaccionalmente.
3. Se busca un pedido incompleto EN_PROCESO/COMPENSANDO ligado a la corrida; se incrementa `IntentoProceso`. Los estados terminales no se reabren.
4. El coordinador consulta reserva, importes y guía persistidos. Reconciliar el transportista resuelve el caso de guía creada con respuesta perdida; no reinicia ciegamente todos los efectos.
5. Tras resolver el pedido interrumpido, cierra la corrida recuperada. Errores agotados o inconsistencias pueden llevar a REQUIERE_REVISION.

Evidencias: [E2E 11](../../tests/evidencias/e2e11-tarea-repetida.json), [12](../../tests/evidencias/e2e12-reinicio-despachos.json) y [13](../../tests/evidencias/e2e13-caida-mongodb.json). El proxy de `tests/integration` empleado para retener la respuesta en escenarios de caída es una herramienta de prueba, no un servicio permanente del Compose base.

## 4. Carga masiva

```mermaid
sequenceDiagram
    participant A as ADMIN / host y remoto
    participant C as cargas-python API
    participant M as MongoDB / GridFS
    participant W as Worker Python
    participant D as Worker despachos-dotnet
    A->>C: POST /cargas multipart archivo + JWT
    C->>M: Guardar entrada GridFS
    C->>M: Transacción Carga y CargaTarea
    C-->>A: 202 con cargaId
    W->>M: Reclamar tarea y renovar lease
    W->>M: Leer archivo de entrada
    W->>W: Parsear y validar bloques de solicitud
    W->>M: Transacciones Pedido RECIBIDO, detalles y resultados por fila
    D->>M: Tomar pedidos con el flujo común de despacho
    W->>M: Guardar reporte GridFS y publicar carga final
    A->>C: GET /cargas/id cada 2 s mientras PROCESANDO
    C-->>A: Estado y contadores
    A->>C: GET /cargas/id/reporte
    C->>M: Leer reporte
    C-->>A: XLSX autenticado
```

El procesamiento de carga y el despacho pueden solaparse: PROCESADA significa importación finalizada, no todos los pedidos despachados. El reporte informa filas ACEPTADA/RECHAZADA/DUPLICADA. No hay transacción que abarque el archivo GridFS y todos los pedidos de la carga; la atomicidad funcional de importación es por bloque. Evidencias: [E2E 15](../../tests/evidencias/e2e15-carga-masiva-500.json) y [16](../../tests/evidencias/e2e16-carga-masiva-trafico.json), con la salvedad de trazabilidad de repeticiones indicada en [LEEME](../../LEEME.md).

## Fuentes de implementación

- [Java: repositorio transaccional](../../services/pedidos-java/src/main/java/pe/reto/pedidos/adapter/out/mongo/MongoRepositorio.java).
- [.NET: coordinador](../../services/despachos-dotnet/src/Despachos.Application/Coordinador.cs), [clientes HTTP](../../services/despachos-dotnet/src/Despachos.Infrastructure/Http/Clientes.cs), [worker](../../services/despachos-dotnet/src/Despachos.Api/Workers/DespachoWorker.cs).
- [Python: worker](../../services/cargas-python/app/application/worker.py) y [persistencia](../../services/cargas-python/app/infrastructure/mongo.py).
