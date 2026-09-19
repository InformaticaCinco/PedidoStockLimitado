# Transportista simulator

Servicio externo ficticio en **Python 3.12 + aiohttp**, puerto **9090**. Crea, consulta y anula guías con idempotencia y fallos controlados. Estado exclusivamente en memoria, sin MongoDB, archivos de persistencia, JWT ni dependencias hacia otros servicios. Reiniciar elimina todas las guías y reinicia correlativos/ciclo de fallos.

## Instalación y ejecución

Desde `services/transportista-simulator`:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
PIP_CACHE_DIR="$PWD/.build/pip-cache" python -m pip install -r requirements.txt
python -m app.main
```

Versiones verificadas: Python **3.12.14**, aiohttp **3.14.3**, pytest **9.1.1**, pytest-asyncio **1.4.0**. Dependencias directas fijadas en `requirements.txt`; versiones transitivas instaladas registradas en `.build/installed-versions.txt`.

`.env.example` es documentación; el servicio lee variables del proceso y no carga `.env` automáticamente.

| Variable | Default | Validación |
|---|---:|---|
| `PORT` | 9090 | Entero 1–65535 |
| `FAILURE_RATE` | 0.3 | Finito entre 0 y 1 |
| `PARTIAL_RATE` | 0.1 | Finito entre 0 y 1 |
| `LATENCY_MS` | 3000 | Entero positivo |

Una configuración inválida produce diagnóstico JSON y salida 2, antes de abrir el servidor. No hay endpoints administrativos para cambiar la configuración.

```bash
# Sin fallos
FAILURE_RATE=0 PARTIAL_RATE=0 python -m app.main
# Fallos intermitentes; partial desactivado para aislar failure
FAILURE_RATE=0.5 PARTIAL_RATE=0 python -m app.main
# Siempre registra la nueva guía y corta la conexión; domina al failure default
PARTIAL_RATE=1.0 python -m app.main
```

## Endpoints

| Método | Ruta | Comportamiento |
|---|---|---|
| GET | `/health` | 200, `{"estado":"UP"}` sin dependencias |
| POST | `/guias` | Idempotency-Key obligatoria; nueva 201, replay 200 |
| GET | `/guias?pedidoId=...` | 200 con numeroGuia y guias; 404 sin activa |
| POST | `/guias/{numero}/anulacion` | 200 idempotente; 404 inexistente |

JSON externo directo, **sin** sobre `{code,statusCode,message,data}`. Ver [CONTRATOS.md](CONTRATOS.md).

## Idempotencia y concurrencia

Misma clave y contenido equivalente devuelve siempre el mismo número; distinto contenido con esa clave da 409. Otra clave con el mismo body **sí crea otra guía**, incluso para el mismo pedido. No se deduplica por pedido ni contenido.

Un `asyncio.Lock` protege comprobación/creación, índices y correlativo (`G-000001`, etc.). Las esperas por fallo quedan fuera del lock: no bloquean health, consultas o replays. Se guardan índices por clave, número y pedido. Anulación marca estado/fecha sin borrar; un replay después de anular devuelve la misma guía y no la reactiva.

GET conserva todas las guías en `guias`, incluidas anuladas. El `numeroGuia` superior es la **primera activa creada**. Si ninguna está activa devuelve 404 y conserva el listado histórico en el body, compatible con la lectura del cliente .NET.

## FAILURE frente a PARTIAL

Para una clave nueva: validar → comprobar clave → evaluar PARTIAL → evaluar FAILURE → creación normal. Claves existentes válidas evitan ambos sorteos.

- **PARTIAL:** crea y registra antes de ejecutar `request.transport.abort()`. No se preparan headers ni se escribe respuesta HTTP. El cliente recibe un error real de transporte; GET y replay recuperan la guía. No es un HTTP 500 disfrazado.
- **FAILURE:** alterna globalmente **500 → 503 → demora → 500…** solo entre creaciones seleccionadas para fallo. Nunca crea guía, consume clave ni incrementa correlativo.
- **Demora:** `2 × LATENCY_MS + 1` milisegundos; luego 503 si el cliente sigue conectado. Default **6001 ms**, mayor que los 5 s del cliente .NET. No se aplica latencia artificial a éxitos/GET/anulación.

Logs JSON por stdout con timestamp, level, servicio, correlationId, método, ruta, pedido/número cuando corresponde y resultado. X-Correlation-Id se conserva en logs y respuesta; si falta se genera. No se registran cuerpos completos, Idempotency-Key, credenciales ni tokens. Se desactiva el access log genérico.

## Pruebas

```bash
python -m pytest -q
python tests/smoke.py
```

Las pruebas HTTP usan listeners **reales** de aiohttp en loopback con puertos temporales, incluidos partial y concurrencia. El smoke abre 9090, comprueba health y siempre detiene su proceso. No utiliza base de datos.

Para ejecutar además las dos pruebas contra el **código real del cliente .NET**, con SDK .NET 10 instalado:

```bash
DOTNET_CLI_HOME="$PWD/.build/dotnet" \
DOTNET_GENERATE_ASPNET_CERTIFICATE=false \
DOTNET_CLI_TELEMETRY_OPTOUT=1 \
DOTNET_CLI_WORKLOAD_UPDATE_NOTIFY_DISABLE=true \
NUGET_HTTP_CACHE_PATH="$PWD/.build/nuget-http" \
dotnet build tests/dotnet-client/Compatibilidad.csproj --disable-build-servers -m:1
RUN_DOTNET_COMPAT=1 python -m pytest -q -s
```

Ese proyecto de prueba compila por enlaces de solo lectura el cliente/contratos .NET existentes; no usa ProjectReference ni escribe en `despachos-dotnet`. Sin `RUN_DOTNET_COMPAT=1`, esos dos casos se omiten explícitamente; el resto se ejecuta normalmente. Se recomienda no ejecutar varias suites sobre el mismo módulo simultáneamente.

La ejecución final incluyó **49/49 pruebas aprobadas**, sin omisiones, y smoke 9090 adicional. Evidencias y comandos exactos en [RESUMEN_FINAL.md](RESUMEN_FINAL.md).

## Límites y pendientes

La memoria volátil y la posibilidad de guías múltiples con claves diferentes son intencionales. .NET debe conservar su clave estable y reconciliar respuestas perdidas. Compose global y presentación integrada con Mongo/Java/.NET quedan fuera de este módulo. Se mantienen los pendientes anteriores de Java (carrera confirmación/anulación y regeneración de correlationId).

Referencias de la biblioteca: [servidor aiohttp](https://docs.aiohttp.org/en/stable/web_reference.html), [almacenamiento por request](https://docs.aiohttp.org/en/stable/web_advanced.html#request-s-storage).
