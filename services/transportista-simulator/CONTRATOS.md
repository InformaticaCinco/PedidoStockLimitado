# Contrato externo del transportista

Base `http://localhost:9090`. Sin autenticación. JSON directo en todas las rutas; no hay sobre común Java/.NET. Los fallos HTTP usan `{"error":"..."}`. No hay endpoint administrativo ni rutas alternativas.

## GET /health

Sin body. **200** `{"estado":"UP"}`. Independiente de cualquier infraestructura y de los sorteos de fallos.

## POST /guias

Headers: `Idempotency-Key` obligatorio y no vacío; `Content-Type: application/json` en clientes. `X-Correlation-Id` opcional.

```json
{"pedidoId":"PED-001","pesoKg":12.4,"zona":"LIMA_METROPOLITANA"}
```

PedidoId es texto no vacío, **sin regex de identificador inventada**. Peso numérico finito > 0 (se rechazan bool, string, null y objetos). Zona: LIMA_METROPOLITANA, LIMA_PROVINCIA o PROVINCIA. JSON incorrecto/tipos incorrectos/campos faltantes: 400. Campos adicionales y claves JSON duplicadas también se rechazan como decisión técnica. Límite de body 64 KiB: 413 al excederlo.

Creación normal **201**:

```json
{"numeroGuia":"G-000001"}
```

Replay, misma clave y mismo contenido **200**, igual body. Esta elección de status es técnica; el reto solo fijaba 201 para creación. La comparación incluye pedidoId/peso/zona, con igualdad decimal: 12.4 y 12.400 son equivalentes; no se altera el texto de pedido/zona ni la clave. Orden/espacios del JSON no afectan la igualdad.

Misma clave y distinto contenido: **409**, sin cambiar la guía. Decisión explícita del documento. Una entrada inválida sigue dando 400 antes de consultar idempotencia.

Diferente clave con body igual: **201 y otra guía**. Ambas se conservan. La clave no se deriva del correlationId. Replay posterior a anulación conserva número y estado ANULADA, sin reactivación.

### Simulación de fallos

Solo aplica a claves nuevas válidas, después de revisar idempotencia:

1. Evaluar PARTIAL_RATE: guardar guía/clave y abortar conexión, **sin respuesta HTTP**. Es recuperable con GET/replay.
2. Si no hubo partial, evaluar FAILURE_RATE. Cada fallo seleccionado avanza el ciclo global 500 → 503 → demora.
3. Si no hubo fallo, crear normalmente y responder 201.

500/503/demora no crean guía ni consumen clave. La demora es **2×LATENCY_MS+1 ms**; al terminar responde 503 si el cliente continúa esperando. El timeout observado depende del timeout del cliente. Default: 6001 ms de demora frente a 5000 ms del cliente .NET actual.

PARTIAL_RATE=1 siempre crea y corta para claves nuevas, incluso con FAILURE_RATE=1. Claves conocidas responden idempotentemente sin volver a sortear ni crear. GET y anulación no simulan fallos.

## GET /guias?pedidoId=...

PedidoId obligatorio no vacío; 400 si falta o está vacío. Con al menos una guía activa: **200**.

```json
{
  "numeroGuia":"G-000001",
  "guias":[
    {"numeroGuia":"G-000001","estado":"ACTIVA"},
    {"numeroGuia":"G-000002","estado":"ANULADA"}
  ]
}
```

`guias` contiene **todas** las guías del pedido en orden de creación. `numeroGuia` superior selecciona la **primera activa**. Esta selección determinista y el campo superior preservan compatibilidad con `TransportistaClient.Consultar` de .NET, que lee ese campo e ignora los adicionales.

Sin activa: **404**, incluso si existen anuladas:

```json
{"error":"No existe guía activa","guias":[{"numeroGuia":"G-000001","estado":"ANULADA"}]}
```

Para un pedido desconocido, `guias:[]`. 404 es el contrato de ausencia adoptado por .NET; no se devuelve 200 con una lista vacía.

## POST /guias/{numero}/anulacion

Sin body funcional ni Idempotency-Key obligatoria. El cliente .NET puede enviar su header de clave estable; la idempotencia de esta operación depende del número de guía.

ACTIVA → ANULADA y fecha UTC de anulación, **200**:

```json
{"numeroGuia":"G-000001","estado":"ANULADA"}
```

Ya ANULADA: **200**, mismo resultado, sin cambiar su fecha ni repetir efecto. Inexistente: **404**, `{"error":"Guía no encontrada"}`. No se elimina físicamente y no hay fallos aleatorios en anulación.

## Correlación, datos y compatibilidad

X-Correlation-Id se recibe, conserva en logs y devuelve en toda respuesta HTTP, incluidos errores. Si falta/se envía vacío se genera UUID técnico. En partial no existe respuesta HTTP; el correlationId queda en log. No se usa para idempotencia.

Estado solo en memoria, índices por clave/número/pedido protegidos por asyncio.Lock. Número secuencial único por ejecución. No se almacenan archivos ni DB; archivos `.build` corresponden únicamente a herramientas/evidencias de pruebas.

Exigido por el reto: rutas, cuerpo, nueva guía 201, idempotencia por clave, múltiples guías con claves distintas, corte TCP real, ciclo de fallos y anulación idempotente.

Decisiones técnicas: replay 200; 409 por contenido diferente (fijado en el prompt de implementación); comparación decimal/JSON estricto; cuerpo directo de errores; límite de body; GET con primera activa + historial completo y 404 sin activa; anulación 200; demora precisa y 503 al finalizarla. Todas compatibles con el cliente .NET real inspeccionado y ejecutado.
