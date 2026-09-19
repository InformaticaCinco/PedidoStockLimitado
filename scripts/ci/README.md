# Pruebas y compilación en Docker

Desde la raíz del repositorio:

```sh
./scripts/run-tests.sh
```

Requiere Bash, Docker y Compose v2. El runner se construye para `linux/amd64`; en ARM necesita la emulación de Docker. No requiere Java, .NET, Python, Node ni Chrome instalados en el anfitrión. La primera ejecución necesita red para descargar imágenes y dependencias.

El mismo comando se usa en `.github/workflows/ci.yml` en cada push y mediante workflow_dispatch. Que el comando local termine correctamente no acredita una ejecución de GitHub Actions.

## Alcance

1. Java 21: Maven verify, unitarias/HTTP y MongoIT; genera el JAR que consumen las integraciones siguientes.
2. .NET 10: solución completa, incluidos MongoReal y JavaReal.
3. Python 3.12 cargas: pytest completo con Mongo y Java reales; compilación de módulos Python.
4. Transportista: pytest completo y los dos casos de compatibilidad del cliente .NET, compilado antes de probarlo.
5. Mongo: pytest del seed/índices, incluyendo integración real con Java.
6. web-host: npm ci, pruebas existentes en Chrome headless y build de producción.
7. admin-mfe: el mismo ciclo con su propia suite.

Las fixtures existentes crean replica sets temporales con mongod 7.0.16 dentro del contenedor y emplean polling de disponibilidad. No se usa el Mongo de la aplicación, no se arrancan servicios del Compose operativo, no se publican puertos y no se monta el socket Docker.

Se copian las fuentes a la imagen excluyendo artefactos/cachés del anfitrión. Las claves demo se leen sin modificarse. Solo `.build/ci/<ejecución>` se monta para los nuevos reportes/logs. PRUEBAS.xlsx, datos y tests/evidencias se excluyen del contexto. La limpieza usa un nombre de proyecto temporal y no elimina volúmenes operativos.

La prueba Python contra Java admite `JAVA_TEST_BINARY`; conserva el valor local previo como fallback. El runner lo fija a su JDK Linux.

El script usa `set -euo pipefail`: un error de build o suite detiene la ejecución y devuelve un código distinto de cero. La limpieza conserva ese código (y falla si la propia limpieza falla después de una ejecución exitosa). Logs completos quedan en la carpeta de reportes; CI los conserva como artifact incluso si falla.

Los 21 escenarios E2E operativos no se vuelven a ejecutar desde este runner: varios resetean datos y sobrescriben las evidencias de entrega. Este comando reúne las suites automatizadas de componentes e integración real existentes, sin inventar casos ni tocar el registro histórico E2E.

## Validación local realizada

El 19/09/2026 se ejecutó `./scripts/run-tests.sh` en Docker linux/amd64 y terminó con **exit 0**, incluida la limpieza. Resultados: Java 43 (30 unitarias/HTTP + 13 MongoIT), .NET 46, cargas 88, transportista 49, Mongo/seed 25, web-host 40 y admin-mfe 27: **318 aprobadas, ninguna omitida**. Pasaron los builds Java/.NET, compilación de módulos Python y ambos builds Angular de producción.

Reportes de esa ejecución: `.build/ci/20260919t061020z-54918/`, con tests.log, XML Java/Python, TRX .NET y exit-code.txt. Antes de esa ejecución se corrigió un error de orquestación: el nombre temporal de proyecto Compose contenía mayúsculas. No se corrigieron ni se ocultaron fallos funcionales. `docker compose config` y `bash -n scripts/run-tests.sh scripts/ci/in-container.sh` terminaron con exit 0.

La ejecución de GitHub Actions sigue pendiente: no se hizo commit ni push y no se afirma CI PASS.
