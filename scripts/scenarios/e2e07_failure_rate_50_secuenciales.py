import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict

BASE = "http://localhost:8080/api/java"
MONGO_URI = "mongodb://localhost:27017/pedidos_stock?directConnection=true"

EVIDENCIA = "tests/evidencias/e2e07-failure-rate-50-secuenciales.json"

os.makedirs("tests/evidencias", exist_ok=True)

TERMINALES = {
    "DESPACHADO",
    "ANULADO",
    "REQUIERE_REVISION"
}


def cmd(args, env=None):
    p = subprocess.run(
        args,
        text=True,
        capture_output=True,
        env=env
    )

    if p.returncode != 0:
        raise RuntimeError(
            f"Comando falló: {' '.join(args)}\n"
            f"STDOUT:\n{p.stdout}\n"
            f"STDERR:\n{p.stderr}"
        )

    return p.stdout.strip()


def mongo(js):
    out = cmd([
        "docker", "compose", "exec", "-T",
        "mongodb",
        "mongosh", "--quiet",
        MONGO_URI,
        "--eval", js
    ])

    lineas = [
        x.strip()
        for x in out.splitlines()
        if x.strip()
    ]

    if not lineas:
        raise RuntimeError("Mongo no devolvió información")

    return json.loads(lineas[-1])


def http(url, method="GET", body=None, token=None):
    headers = {
        "Content-Type": "application/json"
    }

    if token:
        headers["Authorization"] = f"Bearer {token}"

    data = (
        None
        if body is None
        else json.dumps(body).encode("utf-8")
    )

    req = urllib.request.Request(
        url,
        data=data,
        headers=headers,
        method=method
    )

    try:
        with urllib.request.urlopen(
            req,
            timeout=20
        ) as r:
            raw = r.read().decode("utf-8")
            return r.status, json.loads(raw)

    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8")

        try:
            payload = json.loads(raw)
        except Exception:
            payload = {"raw": raw}

        return e.code, payload

    except Exception as e:
        return 0, {"error": str(e)}


resultado = {
    "escenario":
        "E2E 07 - FAILURE_RATE=0.5 con 50 pedidos secuenciales",
    "resultado": "FAIL"
}

try:
    print("1. Restableciendo entorno con FAILURE_RATE=0.5...")

    cmd([
        "docker", "compose",
        "down", "-v"
    ])

    compose_env = os.environ.copy()
    compose_env["FAILURE_RATE"] = "0.5"
    compose_env["PARTIAL_RATE"] = "0"
    compose_env["LATENCY_MS"] = "3000"

    cmd([
        "docker", "compose",
        "up", "-d",
        "--no-build",
        "--wait",
        "--wait-timeout", "240"
    ], env=compose_env)

    print("   Docker Compose: OK")

    print("2. Verificando configuración real del transportista...")

    failure_rate = cmd([
        "docker", "compose", "exec", "-T",
        "transportista-simulator",
        "printenv", "FAILURE_RATE"
    ])

    partial_rate = cmd([
        "docker", "compose", "exec", "-T",
        "transportista-simulator",
        "printenv", "PARTIAL_RATE"
    ])

    latency_ms = cmd([
        "docker", "compose", "exec", "-T",
        "transportista-simulator",
        "printenv", "LATENCY_MS"
    ])

    resultado["configuracion"] = {
        "FAILURE_RATE": failure_rate,
        "PARTIAL_RATE": partial_rate,
        "LATENCY_MS": latency_ms
    }

    print(
        f"   FAILURE_RATE={failure_rate}, "
        f"PARTIAL_RATE={partial_rate}, "
        f"LATENCY_MS={latency_ms}"
    )

    if failure_rate != "0.5":
        raise RuntimeError(
            f"FAILURE_RATE real inesperado: {failure_rate}"
        )

    if partial_rate != "0":
        raise RuntimeError(
            f"PARTIAL_RATE real inesperado: {partial_rate}"
        )

    print("3. Obteniendo productos con stock suficiente en ALM-01...")

    stocks_iniciales = mongo("""
const stocks = db.Stock.find({
    IdAlmacen: "ALM-01",
    IdProducto: {$ne: "SKU-00001"},
    CantidadStock: {$gte: 10}
})
.sort({IdProducto: 1})
.toArray()
.map(s => ({
    sku: s.IdProducto,
    disponible: s.CantidadStock,
    reservado: s.ReservaStock,
    total: s.CantidadStock + s.ReservaStock
}));

print(JSON.stringify(stocks));
""")

    if len(stocks_iniciales) < 2:
        raise RuntimeError(
            "No hay suficientes productos de ALM-01 para la prueba"
        )

    print(
        f"   Productos utilizables: "
        f"{len(stocks_iniciales)}"
    )

    for s in stocks_iniciales:
        print(
            f'   {s["sku"]}: '
            f'{s["disponible"]}/'
            f'{s["reservado"]}/'
            f'{s["total"]}'
        )

    resultado["stockInicial"] = stocks_iniciales

    inicial_por_sku = {
        s["sku"]: s
        for s in stocks_iniciales
    }

    skus = [
        s["sku"]
        for s in stocks_iniciales
    ]

    print("4. Login comprador01...")

    status, login = http(
        f"{BASE}/auth/login",
        "POST",
        {
            "usuario": "comprador01",
            "clave": "Reto2026!"
        }
    )

    if status != 200:
        raise RuntimeError(
            f"Login HTTP {status}: {login}"
        )

    token = login["data"]["accessToken"]

    print("5. Ejecutando 50 pedidos secuenciales...")

    pedidos = []

    for numero in range(1, 51):
        sku = skus[(numero - 1) % len(skus)]

        solicitud_id = (
            f"E2E07-FAILURE-{numero:02d}"
        )

        status_alta, alta = http(
            f"{BASE}/pedidos",
            "POST",
            {
                "solicitudId": solicitud_id,
                "almacenId": "ALM-01",
                "zonaEntrega": "LIMA_METROPOLITANA",
                "items": [
                    {
                        "sku": sku,
                        "cantidad": 1
                    }
                ]
            },
            token
        )

        pedido_id = (
            (alta.get("data") or {}).get("pedidoId")
            if isinstance(alta, dict)
            else None
        )

        if status_alta != 202 or not pedido_id:
            raise RuntimeError(
                f"Pedido {numero}: alta inesperada "
                f"HTTP={status_alta}, respuesta={alta}"
            )

        estado_final = None
        consultas = 0
        inicio = time.time()

        for intento in range(1, 181):
            status_get, detalle = http(
                f"{BASE}/pedidos/{pedido_id}",
                token=token
            )

            consultas = intento

            data = (
                detalle.get("data") or {}
                if isinstance(detalle, dict)
                else {}
            )

            estado = data.get("estado")

            if (
                status_get == 200
                and estado in TERMINALES
            ):
                estado_final = estado
                break

            time.sleep(0.5)

        if estado_final is None:
            raise RuntimeError(
                f"Pedido {numero} no llegó a estado final"
            )

        segundos = round(
            time.time() - inicio,
            2
        )

        item = {
            "numero": numero,
            "solicitudId": solicitud_id,
            "pedidoId": pedido_id,
            "sku": sku,
            "httpAlta": status_alta,
            "estadoFinal": estado_final,
            "polling": consultas,
            "segundos": segundos
        }

        pedidos.append(item)

        print(
            f'   {numero:02d}/50 | '
            f'{sku} | '
            f'{estado_final} | '
            f'{segundos}s'
        )

    resultado["pedidos"] = pedidos

    print("6. Validando estados finales...")

    conteo_estados = Counter(
        p["estadoFinal"]
        for p in pedidos
    )

    resultado["estados"] = dict(
        conteo_estados
    )

    print(
        "   "
        + ", ".join(
            f"{estado}={cantidad}"
            for estado, cantidad
            in sorted(conteo_estados.items())
        )
    )

    if sum(conteo_estados.values()) != 50:
        raise RuntimeError(
            "No existen exactamente 50 resultados finales"
        )

    estados_invalidos = (
        set(conteo_estados.keys())
        - TERMINALES
    )

    if estados_invalidos:
        raise RuntimeError(
            f"Estados finales no permitidos: "
            f"{estados_invalidos}"
        )

    print("7. Validando existencia de los 50 pedidos en MongoDB...")

    cantidad_mongo = mongo("""
print(JSON.stringify({
    cantidad: db.Pedido.countDocuments({
        IdSolicitud: /^E2E07-FAILURE-/
    })
}));
""")

    resultado["cantidadPedidosMongo"] = (
        cantidad_mongo["cantidad"]
    )

    print(
        f'   Pedidos Mongo='
        f'{cantidad_mongo["cantidad"]}'
    )

    if cantidad_mongo["cantidad"] != 50:
        raise RuntimeError(
            "MongoDB no contiene exactamente los 50 pedidos"
        )

    print("8. Validando stock contra despachos efectivos...")

    despachados_por_sku = defaultdict(int)

    for p in pedidos:
        if p["estadoFinal"] == "DESPACHADO":
            despachados_por_sku[p["sku"]] += 1

    skus_json = json.dumps(skus)

    stocks_finales = mongo(f"""
const skus = {skus_json};

const stocks = db.Stock.find({{
    IdAlmacen: "ALM-01",
    IdProducto: {{$in: skus}}
}})
.sort({{IdProducto: 1}})
.toArray()
.map(s => ({{
    sku: s.IdProducto,
    disponible: s.CantidadStock,
    reservado: s.ReservaStock,
    total: s.CantidadStock + s.ReservaStock
}}));

print(JSON.stringify(stocks));
""")

    resultado["stockFinal"] = stocks_finales

    errores_stock = []

    for final in stocks_finales:
        sku = final["sku"]
        inicial = inicial_por_sku[sku]
        despachados = despachados_por_sku[sku]

        esperado_total = (
            inicial["total"]
            - despachados
        )

        print(
            f"   {sku}: "
            f'inicialTotal={inicial["total"]}, '
            f'despachados={despachados}, '
            f'esperadoTotal={esperado_total}, '
            f'final={final["disponible"]}+'
            f'{final["reservado"]}='
            f'{final["total"]}'
        )

        if final["disponible"] < 0:
            errores_stock.append(
                f"{sku}: disponible negativo"
            )

        if final["reservado"] < 0:
            errores_stock.append(
                f"{sku}: reservado negativo"
            )

        if final["total"] != esperado_total:
            errores_stock.append(
                f"{sku}: total esperado "
                f"{esperado_total}, obtenido "
                f'{final["total"]}'
            )

    if errores_stock:
        raise RuntimeError(
            "Inconsistencia de stock: "
            + " | ".join(errores_stock)
        )

    resultado["validaciones"] = {
        "failureRateCorrecto": True,
        "50Pedidos": True,
        "soloEstadosPermitidos": True,
        "stockCuadraConDespachos": True,
        "sinDisponibleNegativo": True,
        "sinReservadoNegativo": True
    }

    resultado["resultado"] = "PASS"

    print()
    print("✅ E2E 07: PASS")

except Exception as e:
    resultado["error"] = str(e)

    print()
    print(f"❌ E2E 07: FAIL - {e}")

with open(
    EVIDENCIA,
    "w",
    encoding="utf-8"
) as f:
    json.dump(
        resultado,
        f,
        ensure_ascii=False,
        indent=2
    )

print(f"Evidencia JSON: {EVIDENCIA}")

raise SystemExit(
    0 if resultado["resultado"] == "PASS" else 1
)
