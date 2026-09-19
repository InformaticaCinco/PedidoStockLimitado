import json
import os
import subprocess
import time
import urllib.error
import urllib.request

BASE = "http://localhost:8080/api/java"
MONGO_URI = "mongodb://localhost:27017/pedidos_stock?directConnection=true"
EVIDENCIA = "tests/evidencias/e2e06-pedido-multilinea-sin-stock.json"

os.makedirs("tests/evidencias", exist_ok=True)


def cmd(args):
    p = subprocess.run(args, text=True, capture_output=True)

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
    headers = {"Content-Type": "application/json"}

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
        with urllib.request.urlopen(req, timeout=20) as r:
            raw = r.read().decode("utf-8")
            return r.status, json.loads(raw)

    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8")

        try:
            payload = json.loads(raw)
        except Exception:
            payload = {"raw": raw}

        return e.code, payload


resultado = {
    "escenario": "E2E 06 - Pedido multilinea con stock insuficiente",
    "resultado": "FAIL"
}

try:
    print("1. Restableciendo entorno limpio...")

    cmd(["docker", "compose", "down", "-v"])

    cmd([
        "docker", "compose",
        "up", "-d",
        "--no-build",
        "--wait",
        "--wait-timeout", "240"
    ])

    print("   Docker Compose: OK")

    print("2. Validando stocks iniciales...")

    inicial = mongo("""
const s1 = db.Stock.findOne({
    IdProducto:"SKU-00001",
    IdAlmacen:"ALM-01"
});

const s2 = db.Stock.findOne({
    IdProducto:"SKU-00002",
    IdAlmacen:"ALM-01"
});

print(JSON.stringify({
    sku00001:{
        disponible:s1?.CantidadStock ?? null,
        reservado:s1?.ReservaStock ?? null
    },
    sku00002:{
        disponible:s2?.CantidadStock ?? null,
        reservado:s2?.ReservaStock ?? null
    }
}));
""")

    resultado["stockInicial"] = inicial

    print(json.dumps(inicial, indent=2))

    if not (
        inicial["sku00001"]["disponible"] == 3
        and inicial["sku00001"]["reservado"] == 0
        and inicial["sku00002"]["disponible"] == 20
        and inicial["sku00002"]["reservado"] == 0
    ):
        raise RuntimeError(
            f"Baseline de stock inesperado: {inicial}"
        )

    print("3. Login comprador01...")

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

    print("4. Registrando pedido de dos líneas...")

    status, alta = http(
        f"{BASE}/pedidos",
        "POST",
        {
            "solicitudId": "E2E06-MULTILINEA-001",
            "almacenId": "ALM-01",
            "zonaEntrega": "LIMA_METROPOLITANA",
            "items": [
                {
                    "sku": "SKU-00002",
                    "cantidad": 1
                },
                {
                    "sku": "SKU-00001",
                    "cantidad": 4
                }
            ]
        },
        token
    )

    pedido_id = (alta.get("data") or {}).get("pedidoId")

    resultado["alta"] = {
        "http": status,
        "pedidoId": pedido_id
    }

    print(
        f"   HTTP={status}, "
        f"pedidoId={pedido_id}"
    )

    if status != 202 or not pedido_id:
        raise RuntimeError(
            "El pedido no fue aceptado con HTTP 202"
        )

    print("5. Esperando estado final mediante polling...")

    estado_final = None
    polling = 0

    for intento in range(1, 121):
        status_get, consulta = http(
            f"{BASE}/pedidos/{pedido_id}",
            token=token
        )

        data = consulta.get("data") or {}
        estado = data.get("estado")

        if estado in {
            "DESPACHADO",
            "ANULADO",
            "REQUIERE_REVISION"
        }:
            estado_final = estado
            polling = intento
            break

        time.sleep(0.5)

    print(
        f"   Estado={estado_final}, "
        f"polling={polling}"
    )

    resultado["estadoFinal"] = estado_final
    resultado["polling"] = polling

    if estado_final != "ANULADO":
        raise RuntimeError(
            f"Se esperaba ANULADO, se obtuvo {estado_final}"
        )

    print("6. Validando atomicidad del stock...")

    final = mongo(f"""
const s1 = db.Stock.findOne({{
    IdProducto:"SKU-00001",
    IdAlmacen:"ALM-01"
}});

const s2 = db.Stock.findOne({{
    IdProducto:"SKU-00002",
    IdAlmacen:"ALM-01"
}});

const p = db.Pedido.findOne({{
    _id:"{pedido_id}"
}});

print(JSON.stringify({{
    estado:p?.IdEstado ?? null,

    sku00001:{{
        disponible:s1?.CantidadStock ?? null,
        reservado:s1?.ReservaStock ?? null
    }},

    sku00002:{{
        disponible:s2?.CantidadStock ?? null,
        reservado:s2?.ReservaStock ?? null
    }},

    reservarStock:
        db.PedidoProceso.countDocuments({{
            IdPedido:"{pedido_id}",
            Paso:"RESERVAR_STOCK"
        }}),

    calcularEnvio:
        db.PedidoProceso.countDocuments({{
            IdPedido:"{pedido_id}",
            Paso:"CALCULAR_ENVIO"
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
        }})
}}));
""")

    resultado["mongo"] = final

    print(json.dumps(
        final,
        indent=2,
        ensure_ascii=False
    ))

    stock_sin_cambios = (
        final["sku00001"]["disponible"] == 3
        and final["sku00001"]["reservado"] == 0
        and final["sku00002"]["disponible"] == 20
        and final["sku00002"]["reservado"] == 0
    )

    sin_efectos_posteriores = (
        final["estado"] == "ANULADO"
        and final["calcularEnvio"] == 0
        and final["generarGuia"] == 0
        and final["confirmarDespacho"] == 0
        and final["guiasMongo"] == 0
    )

    if not stock_sin_cambios:
        raise RuntimeError(
            "Se detectó reserva parcial o modificación de stock"
        )

    if not sin_efectos_posteriores:
        raise RuntimeError(
            "Se ejecutaron pasos posteriores que no correspondían"
        )

    resultado["validaciones"] = {
        "pedidoAnulado": True,
        "skuSinStockSinCambios": True,
        "otraLineaSinCambios": True,
        "sinReservaParcial": True,
        "sinGuia": True
    }

    resultado["resultado"] = "PASS"

    print()
    print("✅ E2E 06: PASS")

except Exception as e:
    resultado["error"] = str(e)

    print()
    print(f"❌ E2E 06: FAIL - {e}")

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
