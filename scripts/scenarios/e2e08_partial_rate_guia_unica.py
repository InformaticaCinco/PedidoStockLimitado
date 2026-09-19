import json
import os
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = "http://localhost:8080/api/java"
TRANSPORTISTA = "http://localhost:9090"
MONGO_URI = "mongodb://localhost:27017/pedidos_stock?directConnection=true"

EVIDENCIA = "tests/evidencias/e2e08-partial-rate-guia-unica.json"

os.makedirs("tests/evidencias", exist_ok=True)


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


def http(url, method="GET", body=None, token=None, timeout=20):
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
        with urllib.request.urlopen(req, timeout=timeout) as r:
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
    "escenario": "E2E 08 - PARTIAL_RATE=1.0 guia unica",
    "resultado": "FAIL"
}

try:
    print("1. Restableciendo entorno con PARTIAL_RATE=1.0...")

    cmd([
        "docker", "compose",
        "down", "-v"
    ])

    compose_env = os.environ.copy()
    compose_env["FAILURE_RATE"] = "0"
    compose_env["PARTIAL_RATE"] = "1.0"
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

    resultado["configuracion"] = {
        "FAILURE_RATE": failure_rate,
        "PARTIAL_RATE": partial_rate
    }

    print(
        f"   FAILURE_RATE={failure_rate}, "
        f"PARTIAL_RATE={partial_rate}"
    )

    if failure_rate != "0":
        raise RuntimeError(
            f"FAILURE_RATE inesperado: {failure_rate}"
        )

    if partial_rate not in ("1", "1.0"):
        raise RuntimeError(
            f"PARTIAL_RATE inesperado: {partial_rate}"
        )

    print("3. Validando stock inicial...")

    inicial = mongo("""
const s = db.Stock.findOne({
    IdProducto:"SKU-00002",
    IdAlmacen:"ALM-01"
});

print(JSON.stringify({
    disponible:s?.CantidadStock ?? null,
    reservado:s?.ReservaStock ?? null
}));
""")

    resultado["stockInicial"] = inicial

    print(
        f'   Stock inicial='
        f'{inicial["disponible"]}/'
        f'{inicial["reservado"]}'
    )

    if not (
        inicial["disponible"] == 20
        and inicial["reservado"] == 0
    ):
        raise RuntimeError(
            f"Baseline incorrecto: {inicial}"
        )

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

    print("5. Registrando pedido...")

    status_alta, alta = http(
        f"{BASE}/pedidos",
        "POST",
        {
            "solicitudId": "E2E08-PARTIAL-001",
            "almacenId": "ALM-01",
            "zonaEntrega": "LIMA_METROPOLITANA",
            "items": [
                {
                    "sku": "SKU-00002",
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

    resultado["alta"] = {
        "http": status_alta,
        "pedidoId": pedido_id
    }

    print(
        f"   HTTP={status_alta}, "
        f"pedidoId={pedido_id}"
    )

    if status_alta != 202 or not pedido_id:
        raise RuntimeError(
            "El pedido no respondió 202 con pedidoId"
        )

    print("6. Esperando estado final mediante polling...")

    estado_final = None
    detalle_final = None
    polling = 0

    for intento in range(1, 181):
        status_get, detalle = http(
            f"{BASE}/pedidos/{pedido_id}",
            token=token
        )

        data = (
            detalle.get("data") or {}
            if isinstance(detalle, dict)
            else {}
        )

        estado = data.get("estado")

        if estado in {
            "DESPACHADO",
            "ANULADO",
            "REQUIERE_REVISION"
        }:
            estado_final = estado
            detalle_final = data
            polling = intento
            break

        time.sleep(0.5)

    resultado["estadoFinal"] = estado_final
    resultado["polling"] = polling
    resultado["detalleFinal"] = detalle_final

    print(
        f"   Estado={estado_final}, "
        f"polling={polling}"
    )

    if estado_final != "DESPACHADO":
        raise RuntimeError(
            f"Se esperaba DESPACHADO, se obtuvo {estado_final}"
        )

    print("7. Validando MongoDB...")

    mongo_final = mongo(f"""
const p = db.Pedido.findOne({{
    _id:"{pedido_id}"
}});

const s = db.Stock.findOne({{
    IdProducto:"SKU-00002",
    IdAlmacen:"ALM-01"
}});

print(JSON.stringify({{
    estado:p?.IdEstado ?? null,

    reservarStock:
        db.PedidoProceso.countDocuments({{
            IdPedido:"{pedido_id}",
            Paso:"RESERVAR_STOCK"
        }}),

    generarGuia:
        db.PedidoProceso.countDocuments({{
            IdPedido:"{pedido_id}",
            Paso:"GENERAR_GUIA"
        }}),

    confirmarDespacho:
        db.PedidoProceso.countDocuments({{
            IdPedido:"{pedido_id}",
            Paso:"CONFIRMAR_DESPACHO"
        }}),

    guiasMongo:
        db.Guia.countDocuments({{
            IdPedido:"{pedido_id}"
        }}),

    disponible:s?.CantidadStock ?? null,
    reservado:s?.ReservaStock ?? null
}}));
""")

    resultado["mongo"] = mongo_final

    print(json.dumps(
        mongo_final,
        indent=2,
        ensure_ascii=False
    ))

    mongo_ok = (
        mongo_final["estado"] == "DESPACHADO"
        and mongo_final["reservarStock"] == 1
        and mongo_final["generarGuia"] == 1
        and mongo_final["confirmarDespacho"] == 1
        and mongo_final["guiasMongo"] == 1
        and mongo_final["disponible"] == 19
        and mongo_final["reservado"] == 0
    )

    if not mongo_ok:
        raise RuntimeError(
            "MongoDB quedó inconsistente"
        )

    print("8. Consultando directamente el transportista...")

    status_t, trans = http(
        f"{TRANSPORTISTA}/guias?"
        f"pedidoId={urllib.parse.quote(pedido_id)}"
    )

    guias = (
        trans.get("guias", [])
        if status_t == 200 and isinstance(trans, dict)
        else []
    )

    activas = [
        g
        for g in guias
        if g.get("estado") == "ACTIVA"
    ]

    resultado["transportista"] = {
        "http": status_t,
        "cantidadGuias": len(guias),
        "guiasActivas": len(activas),
        "respuesta": trans
    }

    print(
        f"   HTTP={status_t}, "
        f"guías={len(guias)}, "
        f"activas={len(activas)}"
    )

    if not (
        status_t == 200
        and len(guias) == 1
        and len(activas) == 1
    ):
        raise RuntimeError(
            "Existe más de una guía o la guía activa no es única"
        )

    resultado["validaciones"] = {
        "partialRateActivo": True,
        "pedidoDespachado": True,
        "unaGuiaMongo": True,
        "unaGuiaActivaTransportista": True,
        "stockCorrecto": True
    }

    resultado["resultado"] = "PASS"

    print()
    print("✅ E2E 08: PASS")

except Exception as e:
    resultado["error"] = str(e)

    print()
    print(f"❌ E2E 08: FAIL - {e}")

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
