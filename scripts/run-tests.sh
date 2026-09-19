#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"
# Unique project and output directory; never use the operational Compose project.
run_id="$(date -u +%Y%m%dt%H%M%Sz)-$$"
export TEST_REPORT_DIR="$repo_root/.build/ci/$run_id"
mkdir -p "$TEST_REPORT_DIR"
compose=(docker compose -p "pedidos-tests-$run_id" -f "$repo_root/docker-compose.test.yml")
cleanup() {
  local status=$?
  trap - EXIT
  "${compose[@]}" down --remove-orphans > "$TEST_REPORT_DIR/cleanup.log" 2>&1 || {
    cat "$TEST_REPORT_DIR/cleanup.log" >&2
    if [[ $status -eq 0 ]]; then status=1; fi
  }
  printf '\nReportes: %s\nResultado del comando: %s\n' "$TEST_REPORT_DIR" "$status"
  exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
"${compose[@]}" config --quiet
printf 'Construyendo runner de pruebas linux/amd64\n'
"${compose[@]}" build tests 2>&1 | tee "$TEST_REPORT_DIR/build.log"
printf '\nEjecutando suites reales dentro de Docker\n'
"${compose[@]}" run --rm -T tests 2>&1 | tee "$TEST_REPORT_DIR/tests.log"
