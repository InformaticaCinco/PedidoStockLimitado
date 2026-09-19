# MongoDB global y seed

Herramientas independientes de los servicios para preparar **MongoDB 7.0.x**, replica set de **un nodo**, base compartida y datos demo. Las transacciones de pedidos/cargas/despachos requieren replica set. Todo este paso vive en `mongo/`; no crea Compose ni Dockerfiles.

## Estructura

- `common.py`: configuración, conexión Majority/Primary y errores de CLI.
- `init/replica_set.py`, `init/wait_for_primary.py`: inicialización idempotente y espera PRIMARY.
- `seed/seed_data.py`, `seed/seed.py`: fixture y upsert/reset.
- `seed/validate.py`, `seed/compatibility.py`: invariantes y consultas focalizadas .NET/cargas.
- `indexes/specs.py`, `indexes/verify_indexes.py`, [INDEXES.md](indexes/INDEXES.md): inventario/convergencia.
- `tests/`: 25 pruebas propias con Mongo real y smoke del JAR Java existente.
- `.build/`: evidencias/cachés/datos temporales; `.venv/`: entorno autónomo, ambos ignorados.

## Instalación

Desde `mongo/`, con Python 3.12:

```bash
python3.12 -m venv .venv
PIP_CACHE_DIR="$PWD/.build/pip-cache" .venv/bin/python -m pip install -r requirements.txt
PIP_CACHE_DIR="$PWD/.build/pip-cache" .venv/bin/python -m pip check
```

Dependencias directas fijadas: PyMongo 4.18.1, bcrypt 5.0.0 y pytest 9.1.1. No se reutiliza ningún entorno de servicios.

## Configuración

| Variable | Predeterminado |
|---|---|
| MONGODB_URI | mongodb://127.0.0.1:27017/?replicaSet=rs0 |
| MONGODB_DATABASE | pedidos_stock |
| MONGODB_REPLICA_SET | rs0 |
| MONGODB_BOOTSTRAP_URI | mongodb://127.0.0.1:27017/?directConnection=true |
| MONGODB_MEMBER_HOST | localhost:27017 |
| MONGODB_TIMEOUT_SECONDS | 30 |
| SEED_MODE | upsert |

`MONGODB_BOOTSTRAP_URI` conecta directamente al mongod incluso antes de existir replica set. `MONGODB_MEMBER_HOST` es el hostname anunciado a los clientes, debe ser resoluble desde ellos. En Compose, usar por ejemplo `mongo:27017` y URI bootstrap `mongodb://mongo:27017/?directConnection=true`, nunca el localhost de otro contenedor. La URI funcional debe incluir replicaSet del mismo nombre.

Todos los servicios deberán recibir **el mismo MONGODB_DATABASE**; sus defaults actuales son distintos. Los scripts rechazan admin/config/local y nombres de base inválidos. `.env.example` solo contiene valores ficticios, sin secretos.

## Arranque local y secuencia de inicialización

Ejemplo para una base local de demostración; mongod se ejecuta en primer plano y se detiene con Ctrl-C al terminar:

```bash
mkdir -p .build/dev-data
../services/pedidos-java/.build/mongo/mongodb-macos-aarch64-7.0.16/bin/mongod \
  --dbpath "$PWD/.build/dev-data" --bind_ip 127.0.0.1 --port 27017 --replSet rs0
```

En otra terminal, desde `mongo/`:

```bash
set -a
source .env.example
set +a
.venv/bin/python -m init.replica_set
.venv/bin/python -m init.wait_for_primary
.venv/bin/python -m seed.seed --upsert
.venv/bin/python -m seed.validate --initial
.venv/bin/python -m indexes.verify_indexes --check-only
```

La inicialización usa replSetInitiate solo cuando falta la configuración. Tolera AlreadyInitialized si otro init gana la carrera; valida nombre y miembro, espera PRIMARY y no ejecuta reconfig ni elimina datos. Una configuración diferente falla explícitamente. Referencia: [rs.initiate de MongoDB 7](https://www.mongodb.com/docs/v7.0/reference/method/rs.initiate/).

## Seed normal, reset y validación

Modo ordinario: `python -m seed.seed` o `--upsert`. Crea colecciones/índices faltantes y maestros ausentes por ID determinista mediante setOnInsert. Nunca borra operaciones, regala stock nuevamente, pone reservas a cero, sobrescribe precios/pesos ni vuelve a salar contraseñas. No modifica artificialmente auditoría. Si un ID del fixture ya pertenece a un maestro con UsuarioCreacion distinto de seed, falla sin apropiárselo; una colisión de clave natural también falla por el índice único.

Reset explícito de desarrollo/demo, **con los servicios detenidos**:

```bash
.venv/bin/python -m seed.seed --reset
.venv/bin/python -m seed.validate --initial
```

Alternativa explícita: SEED_MODE=reset. Los defaults nunca borran. `--upsert` fuerza modo no destructivo aunque el entorno tenga SEED_MODE=reset.

Reset vacía únicamente Pedido/PedidoDetalle/PedidoProceso/Guia/Worker/Carga/CargaDetalle/CargaTarea/RefreshToken/fs.files/fs.chunks; borra maestros cuyos IDs pertenecen al fixture y UsuarioCreacion=seed y los restaura. No usa dropDatabase, no elimina colecciones desconocidas ni maestros ajenos. Limpieza y reseed comparten una transacción Snapshot/Majority/Primary. Conflictos de índices/propiedad se detectan antes de confirmar borrados. Los índices se conservan/convergen, no se destruyen para ocultar conflictos.

`--initial` exige fixture exacto, reservas cero, SKU especial=3, auditoría inicial y operaciones vacías. Después de usar la demo:

```bash
.venv/bin/python -m seed.validate
```

Este modo comprueba estructura, referencias, tipos, conteos mínimos, estados, índices y tarifas, pero conserva stock/precios/hashes operacionales válidos y los informa como diferencias. No exige 3 unidades después de que se consumieron. Ambos modos fallan con salida distinta de cero si se violan invariantes. Si una base contiene maestros ajenos adicionales, reset los preserva; `--initial` puede detectar que ya no es el fixture limpio exacto.

No hay migración automática de fixtures de futuras versiones: upsert preserva datos; reset recrea los IDs del fixture actual. Un cambio de fixture que deba conservar auditoría histórica requerirá una migración explícita posterior.

## Dataset y credenciales

214 maestros: 3 Rol, 13 Estado, 44 Usuario (1 ADMIN, 3 VENDEDOR, 40 COMPRADOR), 40 Cliente, 3 Almacen, 3 UsuarioAlmacen, 40 Producto, 40 Stock, 3 Zona, 24 ZonaTramo y 1 Transporte. Once colecciones operativas vacías en un inicio limpio/reset.

**SKU-00001 / ALM-01** es el producto de las últimas tres unidades: disponible 3, reservado 0, total 3, peso 0.25 kg. Resto de stock 20/30/50 en ciclo. Vendedores repartidos en tres almacenes, 14/13/13 productos. Todos los maestros activables tienen IdEstado explícito ACTIVO.

Tres zonas oficiales; ocho intervalos contiguos por zona, [0,2500), con tarifas Decimal128 y dos decimales. Cubre incluso 20×50×2=2000 kg, máximo conservador del fixture. Un único Transporte activo, TRANS-1.

Datos/relaciones/tarifas: [SEED_DATA.md](seed/SEED_DATA.md). Credenciales exclusivamente demo: [credentials.md](seed/credentials.md), contraseña Reto2026!, logins admin/vendedor01..03/comprador01..40. Mongo almacena ClaveHash BCrypt `$2a$`, compatible con Java, nunca password plano. Se eligió explícitamente ese prefijo soportado por [bcrypt](https://pypi.org/project/bcrypt/).

## Pruebas focalizadas

```bash
.venv/bin/python -m pytest -q
```

Solo recoge `mongo/tests/`: **no ejecuta suites de otros servicios**. Levanta MongoDB 7 real en puerto efímero, rsMongoSeed, bases `mongo_seed_it_<uuid>` y `mongo_seed_java_<uuid>`, dbpath/logs bajo `.build`. Al finalizar elimina sus bases aisladas y detiene Mongo/Java. El binario se lee del módulo Java sin modificarlo. Variables opcionales de test: MONGODB_TEST_BINARY y JAVA_TEST_BINARY.

Prueba de Java: arranca su JAR ya compilado, login ADMIN/VENDEDOR/COMPRADOR y GET de stock especial. No recompila Java. La compatibilidad .NET y cargas se demuestra con consultas Python propias fieles al código inspeccionado sobre Mongo real, incluyendo fronteras de tarifa y SKU-00015/ALM-01 como negativo. No se arrancan .NET, cargas ni transportista y no se afirma despacho end-to-end.

Resultados realmente ejecutados y correcciones: [RESUMEN_FINAL.md](RESUMEN_FINAL.md). Esquema inspeccionado: [SCHEMA_NOTES.md](SCHEMA_NOTES.md).

## Preparación para Compose

El próximo paso deberá instalar requirements.txt en un job autónomo con cwd mongo/ y conectar esta secuencia:

1. mongod MongoDB 7 con --replSet y hostname de miembro resoluble.
2. `python -m init.replica_set`.
3. `python -m init.wait_for_primary`.
4. `python -m seed.seed --upsert`.
5. `python -m seed.validate` y `python -m indexes.verify_indexes --check-only`.
6. Iniciar servicios con la misma URI/base.

Usar validación normal en reinicios: `--initial` solo corresponde al arranque limpio/reset. Configurar SEED_MODE=upsert, nunca reset automático por restart. Este paso no modifica docker-compose.yml.

Pendientes externos preservados: Java reemplaza Correlation-Id; anulación después de confirmar stock puede quedar REQUIERE_REVISION; cargas documenta huérfanos GridFS; transportista vive en memoria. Los PDF no estaban disponibles; no se afirma haberlos leído.

Índices equivalentes con otro nombre: el verificador los conserva, como exige el contrato. Se comprobó que MongoDB 7 puede responder código 85 si después un servicio pide el nombre canónico de ese mismo índice. Los índices nuevos del seed tienen los nombres canónicos y el smoke Java los aceptó. Para una base preexistente con aliases, revisar `equivalent.actualName` y coordinar su migración antes de arrancar servicios; detalle en INDEXES.md.
