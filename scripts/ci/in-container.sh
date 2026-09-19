#!/usr/bin/env bash
set -euo pipefail
cd /work
# The source is copied into the image. Nothing writes into the checkout/evidence.
trap 'status=$?; printf "%s\n" "$status" > /reports/exit-code.txt' EXIT
export PEDIDOS_TEST_JAR=/work/services/pedidos-java/target/pedidos-1.0.0.jar
export PEDIDOS_TEST_PRIVATE_KEY=/work/services/pedidos-java/keys/reto-private.pem
export PEDIDOS_TEST_PUBLIC_KEY=/work/services/pedidos-java/keys/reto-public.pem
export RUN_DOTNET_COMPAT=1
printf 'Arquitectura: '; uname -m
java -version
mvn -version
dotnet --version
python3 --version
node --version
"$MONGODB_TEST_BINARY" --version
"$CHROME_BIN" --version

printf '\n=== pedidos-java: compilación, unitarias/HTTP y Mongo real ===\n'
(cd services/pedidos-java && mvn -B -ntp verify)
cp -r services/pedidos-java/target/surefire-reports /reports/java-unit
cp -r services/pedidos-java/target/failsafe-reports /reports/java-mongo

printf '\n=== despachos-dotnet: todas las pruebas, Mongo y Java reales ===\n'
(cd services/despachos-dotnet && dotnet test Despachos.slnx --logger 'trx;LogFileName=despachos.trx' --results-directory /reports/dotnet)

printf '\n=== cargas-python: dominio, HTTP, Mongo y Java reales ===\n'
(cd services/cargas-python && .venv/bin/python -m compileall -q app && .venv/bin/python -m pytest -q --junitxml=/reports/cargas.xml)

printf '\n=== transportista-simulator: HTTP y compatibilidad cliente .NET ===\n'
(cd services/transportista-simulator && dotnet build tests/dotnet-client/Compatibilidad.csproj && .venv/bin/python -m compileall -q app && .venv/bin/python -m pytest -q --junitxml=/reports/transportista.xml)

printf '\n=== mongo: seed, índices e integración Java real ===\n'
(cd mongo && .venv/bin/python -m pytest -q --junitxml=/reports/mongo.xml)

for component in web-host admin-mfe; do
  printf '\n=== %s: pruebas Angular/Chrome y build producción ===\n' "$component"
  (cd "frontend/$component" && npm ci && npm test && npm run build)
done
printf '\nTodas las suites y compilaciones finalizaron correctamente.\n'
