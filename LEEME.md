# Despacho de pedidos con stock limitado

Solución del reto **PedidoStockLimitado**: recepción de pedidos individuales y por Excel, reserva concurrente de existencias, despacho asíncrono con guía externa, reintentos, recuperación y compensaciones. Incluye una aplicación web por roles y un microfrontend ADMIN. MongoDB es la única base de datos; el trabajo pendiente se conserva en sus colecciones.

Este documento describe el código y las evidencias disponibles al cierre documental del 19/09/2026. No representa una nueva ejecución de pruebas.

## Arquitectura y acceso

| Componente Compose | Tecnología comprobada en proyecto/Dockerfile | Puerto publicado → contenedor |
|---|---|---|
| web-host | Angular 17.3.12, Material 17.3.10, Module Federation 17.0.8; build Node 20; Nginx 1.27-alpine | 8080 → 80 |
| admin-mfe | Angular 17.3.12, Material/Lucide; Remote `./Routes`, export `ADMIN_ROUTES`; Node 20/Nginx 1.27-alpine | 8081 → 80 |
| pedidos-java | Java 21, Javalin 6.7.0, Dagger 2.56.2, Maven 3.9.9; JRE Temurin 21.0.10_7 | 8090 → 8090 |
| despachos-dotnet | .NET 10; SDK 10.0.201 y ASP.NET runtime 10.0.5 | 8091 → 8091 |
| cargas-python | Python 3.12.14, FastAPI 0.141.1, PyMongo 4.18.1, openpyxl 3.1.5 | 8092 → 8092 |
| transportista-simulator | Python 3.12.14, aiohttp 3.14.3 | 9090 → 9090 |
| mongodb | MongoDB 7.0.16, replica set `rs0` de un nodo | 27017 → 27017 |
| mongo-init | Python 3.12.14; inicialización, índices y seed | Sin puerto; tarea de arranque |

El navegador entra por [web-host](http://localhost:8080). Su Nginx envía `/api/java/`, `/api/despachos/` y `/api/cargas/` al servicio correspondiente. ADMIN descarga de forma diferida `http://localhost:8081/remoteEntry.js`; el remoto usa el HttpClient y la sesión del host. COMPRADOR/VENDEDOR no necesitan descargarlo.

Java aplica reglas de catálogo, identidad, pedidos y stock mediante arquitectura hexagonal. .NET coordina el despacho y consulta MongoDB; las mutaciones de stock se realizan llamando a Java. Python guarda archivos en GridFS y crea pedidos en MongoDB para que el mismo worker .NET los procese. El simulador mantiene guías en memoria y no usa otra base de datos.

Ver [flujo de servicios](docs/diagramas/flujo-servicios.md) y [modelo visual DrawDB](https://www.drawdb.app/share/UqbNEYSq4dIdhbgsXcH2GAwZ). `ModelamientoDatos.pdf` forma parte de la documentación de entrega indicada por el responsable, junto con `Requerimiento.pdf` y `Diagrama.pdf`. **PENDIENTE DE CIERRE:** los tres PDF no se localizaron dentro de esta copia; adjuntarlos y contrastar su contenido antes de entregar. No se afirma haberlos leído ni validado el contenido del enlace externo.

## Levantar desde cero

Requisitos: Docker Engine/Docker Desktop con Compose v2, puertos de la tabla libres y capacidad para ejecutar `linux/amd64` (con emulación si el equipo es ARM). Ejecutar desde la raíz `PedidoStockLimitado`. No se requieren SDK locales para levantar el sistema.

Compose tiene valores demo por defecto; [.env.compose.example](.env.compose.example) documenta las variables opcionales. Para personalizarlas, crear un `.env` local o exportarlas en el entorno. Las claves incluidas son exclusivamente de laboratorio.

```sh
docker compose config --quiet
docker compose build
docker compose up -d --no-build --wait --wait-timeout 240
docker compose ps -a
```

La construcción local es el camino reproducible descrito aquí: no se presupone que las imágenes propias estén publicadas. Mongo inicia `rs0`; `mongo-init` espera al primario, crea índices y aplica seed en modo `upsert`. Su salida exitosa como tarea finalizada es normal. Los servicios dependen de esta inicialización y el host espera los healthchecks de backend/remoto. Los healthchecks básicos no sustituyen la verificación funcional de dependencias.

Abrir `http://localhost:8080`, iniciar sesión y utilizar el menú del rol. Para diagnóstico: `docker compose logs --tail=100 pedidos-java despachos-dotnet cargas-python`.

Para detener conservando contenedores/volumen:

```sh
docker compose stop
```

Para retirar contenedores y red conservando el volumen:

```sh
docker compose down
```

Reset completo **destructivo para los datos de laboratorio** (borra pedidos, cargas, sesiones y stock del volumen; no borra los archivos de evidencias del repositorio):

```sh
docker compose down -v
docker compose up -d --no-build --wait --wait-timeout 240
```

Sin `-v`, el seed `upsert` conserva datos operativos y no restituye existencias consumidas. El stock inicial del fixture no debe confundirse con el estado actual después de las pruebas. El simulador pierde sus guías al reiniciar su proceso aunque se conserve MongoDB.

## Usuarios demo

Contraseña inicial común: **`Reto2026!`**. Datos ficticios definidos en [seed_data.py](mongo/seed/seed_data.py) y [credenciales](mongo/seed/credentials.md).

| Usuario | Rol | Relación |
|---|---|---|
| `admin` | ADMIN | Administración, cargas y revisión |
| `vendedor01` | VENDEDOR | `ALM-01`, SKU-00001 a SKU-00014 |
| `vendedor02` | VENDEDOR | `ALM-02`, SKU-00015 a SKU-00027 |
| `vendedor03` | VENDEDOR | `ALM-03`, SKU-00028 a SKU-00040 |
| `comprador01` … `comprador40` | COMPRADOR | `CLI-0001` … `CLI-0040` |

El seed contiene 44 usuarios, 40 productos y tres almacenes. Mongo almacena BCrypt en `ClaveHash`, no contraseñas en claro. El seed normal conserva cambios operativos de contraseña.

## Seguridad y JWT

Java autentica y firma access tokens **RS256**. Publica la clave pública en `/.well-known/jwks.json` dentro del sobre común: .NET y Python extraen `data.keys` y validan el JWT de forma independiente (firma, expiración, issuer y audience), además de rol/identidad según endpoint. No comparten la clave privada. En Compose el access token dura 900 segundos y el refresh 604800 segundos; Java rota/revoca refresh tokens persistidos como hash.

El host gestiona sesión, Bearer y refresh; el remoto ADMIN no implementa otro login. Las operaciones internas de stock usan `X-Internal-Key` desde .NET a Java. Roles, pertenencia e identidad se verifican en backend, sin confiar en un `clienteId` enviado por el comprador. Las claves RSA demo y la clave interna del reto deben sustituirse antes de un despliegue productivo.

## Stock, concurrencia e idempotencia

`Stock.CantidadStock` representa unidades **disponibles**, `ReservaStock` las comprometidas y `total = disponible + reservado`. No se vuelve a restar la reserva para calcular disponible. El fixture de SKU-00001 en ALM-01 comienza en **3/0/3**.

La reserva de `q` unidades aplica `disponible -= q`, `reservado += q`; liberar aplica la operación inversa; confirmar reduce solo `reservado`. Java usa filtros condicionales y transacciones MongoDB con snapshot/majority que incluyen todas las líneas, el estado de reserva y el registro del paso. Si falta stock en una línea, ninguna queda reservada. No depende de locks de memoria ni de una lectura de stock seguida de una escritura sin condición.

`solicitudId` se persiste como `Pedido.IdSolicitud` con índice único. Igual ID y contenido canónico devuelve el pedido existente (200 frente al 202 del alta); contenido diferente devuelve 409. Python usa la misma huella para la interoperabilidad de solicitudes individuales y Excel. `EstadoReserva` evita repetir efectos de stock; `PedidoProceso` conserva pasos e intentos.

Ver [decisión 01: consistencia](docs/decisiones/01-consistencia-stock-mongodb.md) y [decisión 02: idempotencia](docs/decisiones/02-idempotencia-y-repeticion.md).

## Despacho, recuperación y compensaciones

El worker .NET toma pedidos RECIBIDO, reserva, calcula envío con `ZonaTramo`, genera/reconcilia guía, confirma stock y termina DESPACHADO. Mantiene una corrida `Worker` con `LeaseOwner`, `LeaseVersion`, `LeaseHeartbeat` e `Intentos`. El lease de Compose es 30 segundos, con heartbeat cada tercio; la recuperación reclama una corrida vencida y continúa el pedido interrumpido sin reabrir estados terminales. Las escrituras comprueban la propiedad del lease dentro de transacciones.

La clave estable `Idempotency-Key` y la consulta por `pedidoId` permiten reconciliar una guía cuya respuesta se perdió. `GuiaIntentada` se registra antes de generar el efecto externo. Los reintentos son acotados; agotamiento o inconsistencias pueden terminar en REQUIERE_REVISION para intervención ADMIN.

Una anulación compatible inicia compensación: primero **ANULAR_GUIA**, después **LIBERAR_STOCK**, y solo entonces ANULADO si se verifican las condiciones. DESPACHADO rechaza anulación con 409. Existe una limitación explícita: si la anulación llega después de la confirmación irreversible de stock y antes del cierre .NET, queda REQUIERE_REVISION; no se simula una restitución ya implementada.

## Transportista y fallos

Compose arranca con `FAILURE_RATE=0`, `PARTIAL_RATE=0`, `LATENCY_MS=3000`. El simulador fuera de Compose tiene otros valores por defecto (0.3/0.1); se debe distinguir la configuración del despliegue.

Para una sesión de laboratorio con fallos intermitentes:

```sh
FAILURE_RATE=0.5 PARTIAL_RATE=0 docker compose up -d --no-build --force-recreate transportista-simulator
```

Para respuesta perdida después de crear la guía:

```sh
FAILURE_RATE=0 PARTIAL_RATE=1 docker compose up -d --no-build --force-recreate transportista-simulator
```

`FAILURE_RATE` puede producir error HTTP o espera que provoca timeout sin crear la nueva guía. `PARTIAL_RATE` crea la guía y corta la conexión; .NET debe consultar antes de volver a crear. Son tasas de simulación, no garantía de un conteo exacto de fallos. Recrear el simulador borra su estado en memoria: usar estos comandos solo al preparar el escenario, no como recuperación de guías existentes. Restaurar explícitamente ambas tasas a cero para la operación demo normal.

## Carga Excel

Archivo entregado: [datos/pedidos-masivo.xlsx](datos/pedidos-masivo.xlsx), con generador [datos/generar_pedidos_masivo.py](datos/generar_pedidos_masivo.py). ADMIN lo selecciona en Carga masiva. Python recibe multipart `archivo`, responde 202 con `cargaId`, guarda entrada/reporte en GridFS y procesa una `CargaTarea` persistente con lease y reintentos.

Columnas: `SOLICITUDID`, `CLIENTEID`, `ALMACENID`, `SKU`, `CANTIDAD`, `ZONAENTREGA`, `FECHASOLICITUD`. Se validan bloques consecutivos de una solicitud; una fila inválida rechaza el bloque. No se reserva stock al importar: se crean pedidos RECIBIDO y el worker común arbitra las existencias. ACEPTADA significa pedido registrado, no necesariamente DESPACHADO.

La UI consulta cada dos segundos mientras PROCESANDO y descarga XLSX autenticado al finalizar. Conserva hasta diez IDs de cargas recientes de la sesión; no hay endpoint de historial global ni de detalle de filas por API. Límite backend configurado: 10485760 bytes. Ver [contrato Python](services/cargas-python/CONTRATOS.md) para validaciones y estados.

## Escenarios y evidencias existentes

Los 21 escenarios fueron ejecutados correctamente según el cierre comunicado por el responsable y los resultados registrados. Se revisaron los JSON/logs de [tests/evidencias/](tests/evidencias/) y [PRUEBAS.xlsx](PRUEBAS.xlsx), que contiene 48 filas de casos/repeticiones con estado OK. No se volvieron a ejecutar ni se modificaron esos archivos durante este cierre documental.

Listado exacto de los 21 archivos presentes en `scripts/scenarios`:

| E2E | Script real |
|---|---|
| 01 | [e2e01_pedido_correcto.py](scripts/scenarios/e2e01_pedido_correcto.py) |
| 02 | [e2e02_idempotencia_tres_envios.py](scripts/scenarios/e2e02_idempotencia_tres_envios.py) |
| 03 | [e2e03_conflicto_solicitud.py](scripts/scenarios/e2e03_conflicto_solicitud.py) |
| 04 | [e2e04_repeticiones_02_10.py](scripts/scenarios/e2e04_repeticiones_02_10.py) |
| 05 | [e2e05_repeticiones_02_10.py](scripts/scenarios/e2e05_repeticiones_02_10.py) |
| 06 | [e2e06_pedido_multilinea_sin_stock.py](scripts/scenarios/e2e06_pedido_multilinea_sin_stock.py) |
| 07 | [e2e07_failure_rate_50_secuenciales.py](scripts/scenarios/e2e07_failure_rate_50_secuenciales.py) |
| 08 | [e2e08_partial_rate_guia_unica.py](scripts/scenarios/e2e08_partial_rate_guia_unica.py) |
| 09 | [e2e09_anulacion_durante_proceso.py](scripts/scenarios/e2e09_anulacion_durante_proceso.py) |
| 10 | [e2e10_anulacion_estados_finales.py](scripts/scenarios/e2e10_anulacion_estados_finales.py) |
| 11 | [e2e11_tarea_repetida.py](scripts/scenarios/e2e11_tarea_repetida.py) |
| 12 | [e2e12_reinicio_despachos.py](scripts/scenarios/e2e12_reinicio_despachos.py) |
| 13 | [e2e13_caida_mongodb.py](scripts/scenarios/e2e13_caida_mongodb.py) |
| 14 | [e2e14_caida_transportista.py](scripts/scenarios/e2e14_caida_transportista.py) |
| 15 | [e2e15_carga_masiva_500.py](scripts/scenarios/e2e15_carga_masiva_500.py) |
| 16 | [e2e16_carga_masiva_trafico.py](scripts/scenarios/e2e16_carga_masiva_trafico.py) |
| 17 | [e2e17_autenticacion.py](scripts/scenarios/e2e17_autenticacion.py) |
| 18 | [e2e18_autorizacion_roles.py](scripts/scenarios/e2e18_autorizacion_roles.py) |
| 19 | [e2e19_pertenencia.py](scripts/scenarios/e2e19_pertenencia.py) |
| 20 | [e2e20_suplantacion_parametro.py](scripts/scenarios/e2e20_suplantacion_parametro.py) |
| 21 | [e2e21_validacion_seguridad.py](scripts/scenarios/e2e21_validacion_seguridad.py) |

E2E 04, 05 y 16 se ejecutaron diez veces según el registro de entrega y PRUEBAS.xlsx. Alcance verificable de la evidencia conservada:

- E2E 04 y 05: cada JSON registra repetición 01 como `PASS`, tipo `validacion manual previa`, y nueve resultados detallados 02–10, todos PASS. La primera no tiene el mismo detalle técnico que las otras nueve.
- E2E 16: existen el archivo base y `e2e16-rep-2` a `e2e16-rep-10`, todos PASS. **PENDIENTE DE CIERRE:** el JSON base y el de repetición 10 son idénticos y tienen el mismo `cargaId`; solo se pueden distinguir nueve cargas. Recuperar evidencia independiente de la primera ejecución sin sobrescribir la actual. Esto es una limitación de trazabilidad, no una afirmación de fallo funcional.

Resultados concretos conservados: E2E 04 muestra tres DESPACHADO y 37 ANULADO para 40 competidores por tres unidades; E2E 05 muestra un alta 202 y 39 repeticiones 200, un pedido y una guía. E2E 06 demuestra rollback multilínea. E2E 08 reconcilia una guía tras respuesta parcial; E2E 09 registra compensación y restitución; E2E 11–13 documentan recuperación/reinicio. E2E 14 termina REQUIERE_REVISION con stock 19 disponible/1 reservado, sin guía, tras tres fallos. E2E 15 registra 500 filas: 439 aceptadas, 53 rechazadas y 8 duplicadas; su [reporte](tests/evidencias/e2e15-reporte.xlsx) está conservado. E2E 16 registra tres despachos entre 40 competidores. E2E 17–21 cubren autenticación, roles, pertenencia, suplantación y validación de entradas/logs.

Los scripts se ejecutan desde la raíz con `python3 scripts/scenarios/<archivo>.py`, pero **no son verificaciones de solo lectura**: varios restablecen datos, detienen servicios y sobrescriben la evidencia de su nombre. No ejecutarlos sobre las evidencias de entrega sin preparar un entorno/copia independiente. E2E 09/12/13 usan overrides/proxy en `tests/integration`; E2E 18 utiliza Playwright del host y requiere su navegador instalado. Revisar cada script antes de reproducirlo.

## Comandos de pruebas por componente

Estos son comandos existentes para reproducción futura, no ejecuciones realizadas en esta tarea. Ejecutarlos dentro del directorio indicado, con SDK/dependencias ya preparados según su README.

| Directorio | Comando |
|---|---|
| `services/pedidos-java` | `mvn test` (Java 21); `mvn package` para JAR |
| `services/despachos-dotnet` | `dotnet test Despachos.slnx --filter 'Categoria!=MongoReal&Categoria!=JavaReal'` (.NET 10) |
| `services/cargas-python` | `.venv/bin/python -m pytest -q tests/test_domain.py tests/test_api.py` |
| `services/transportista-simulator` | `python -m pytest -q` en su entorno Python 3.12 |
| `mongo` | `.venv/bin/python -m pytest -q` según requisitos de Mongo de su README |
| `frontend/web-host` | `npm test`; `npm run build` |
| `frontend/admin-mfe` | `npm test`; `npm run build` |

Java `mvn verify` requiere `MONGODB_TEST_URI` o `MONGODB_TEST_BINARY` para integración real; sin ellos puede omitir esa parte. .NET y Python documentan pruebas Mongo/Java reales por separado en sus README. Frontends requieren Node compatible con Angular 17 y Chrome para Karma. No interpretar una prueba omitida como aprobada.

## Integración continua e imágenes

El workflow [.github/workflows/ci.yml](.github/workflows/ci.yml) compila y ejecuta las suites en cada `push` y admite `workflow_dispatch`, con runner Linux. Reutiliza el comando único `./scripts/run-tests.sh`: las pruebas corren dentro de Docker `linux/amd64`, incluidos MongoDB y las integraciones reales disponibles. Ver [instrucciones del runner](scripts/ci/README.md). Los reportes nuevos se guardan en `.build/ci/`; las evidencias E2E previas no se sobrescriben. **PENDIENTE DE CIERRE:** primera ejecución verificable en GitHub Actions; crear el workflow o aprobar localmente no equivale a CI PASS.

Todas las entradas Compose fijan `platform: linux/amd64`. La siguiente tabla describe referencias declaradas, no prueba publicación ni sustituye un digest de registro.

| Imagen declarada | Versión | Plataforma declarada | Publicación/digest verificable |
|---|---|---|---|
| `pedido-stock/mongo-tools` | 1.0.0 | linux/amd64 | PENDIENTE DE CIERRE |
| `pedido-stock/pedidos-java` | 1.0.0 | linux/amd64 | PENDIENTE DE CIERRE |
| `pedido-stock/despachos-dotnet` | 1.0.0 | linux/amd64 | PENDIENTE DE CIERRE |
| `pedido-stock/cargas-python` | 1.0.0 | linux/amd64 | PENDIENTE DE CIERRE |
| `pedido-stock/transportista-simulator` | 1.0.0 | linux/amd64 | PENDIENTE DE CIERRE |
| `pedido-stock/web-host` | 1.0.0 | linux/amd64 | PENDIENTE DE CIERRE |
| `pedido-stock/admin-mfe` | 1.0.0 | linux/amd64 | PENDIENTE DE CIERRE |
| `mongo` (base externa) | 7.0.16 | linux/amd64 | PENDIENTE DE CIERRE: digest usado en entrega |

No se encontraron aquí manifiestos de publicación que permitan cerrar registro/digests. No se inventan SHA256 ni se confunde un hash de build Angular o ID local de imagen con un digest publicado.

## Límites y cierre

Una instancia por servicio y MongoDB de un nodo no ofrecen alta disponibilidad. El simulador pierde estado al reiniciarse. Existen el caso de anulación posterior a confirmación descrito arriba, renovación de correlationId en el adaptador HTTP Java (no hay continuidad completa del header entrante), posibles archivos huérfanos GridFS ante interrupción entre archivo y metadatos, y métricas ADMIN derivadas/paginadas, sin BI global.

Algunos README/RESUMEN de módulos conservan pendientes históricos de Compose o integración que ya existen en el código actual. Este documento distingue el estado final verificable; no se reescribió el historial de esos módulos. La [decisión 03](docs/decisiones/03-arquitectura-productiva.md) separa implementación del reto y evolución propuesta para producción.

**PENDIENTE DE CIERRE:** al validar el nuevo CI, Git ya está inicializado pero no contiene archivos rastreados; `git diff --stat` devuelve salida vacía. No se hizo commit ni push. Completar además PDF, trazabilidad de E2E 16, CI y publicación/digests indicados arriba.

**PENDIENTE: completar tiempo real antes de entregar.**

Uso de herramientas y supervisión: [IA.md](IA.md).
