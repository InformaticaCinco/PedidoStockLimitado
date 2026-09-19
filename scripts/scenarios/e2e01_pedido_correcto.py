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
EVIDENCIA = "tests/evidencias/e2e01-pedido-correcto.json"

os.makedirs("tests/evidencias", exist_ok=True)


def cmd(args):
    p = subprocess.run(args, text=True, capture_output=True)
    if p.returncode != 0:
        raise RuntimeError(
            f"Comando falló: {' '.join(args)}\n"
            f"{p.stdout}\n{p.stderr}"
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
    return json.loads(
        [x.strip() for x in out.splitlines() if x.strip()][-1]
    )


def http(url, method="GET", body=None, token=None):
    headers = {"Content-Type": "application/json"}

    if token:
        headers["Authorization"] = f"Bearer {token}"

    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=data,
        headers=headers,
        method=method
    )

    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            raw = r.read().decode()
            return r.status, json.loads(raw)

    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        return e.code, json.loads(raw)


resultado = {
    "escenario": "E2E 01 - Pedido correcto FAILURE_RATE=0",
    "resultado": "FAIL"
}

try:
    print("1. Restableciendo entorno limpio...")

    cmd(["docker", "compose", "down", "-v"])

    cmd([
        "docker", "compose", "up",
        "-d", "--no-build",
        "--wait", "--wait-timeout", "240"
    ])

    print("   Docker Compose: OK")

    print("2. Validando stock inicial SKU-00002...")

    inicial = mongo("""
const s = db.Stock.findOne({
    IdProducto:"SKU-00002",
    IdAlmacen:"ALM-01"
});
print(JSON.stringify({
    disponible:s.CantidadStock,
    reservado:s.ReservaStock
}));
""")

    resultado["stockInicial"] = inicial

    print(
        f'   Stock inicial='
        f'{inicial["disponible"]}/'
        f'{inicial["reservado"]}'
    )

    if inicial != {"disponible": 20, "reservado": 0}:
        raise RuntimeError(f"Stock inicial incorrecto: {inicial}")

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
        raise RuntimeError(f"Login HTTP {status}: {login}")

    token = login["data"]["accessToken"]

    print("4. Registrando pedido correcto...")

    status, alta = http(
        f"{BASE}/pedidos",
        "POST",
        {
            "solicitudId": "E2E01-PEDIDO-CORRECTO",
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

    pedido_id = (alta.get("data") or {}).get("pedidoId")

    resultado["alta"] = {
        "http": status,
        "pedidoId": pedido_id
    }

    print(f"   HTTP={status}, pedidoId={pedido_id}")

    if status != 202 or not pedido_id:
        raise RuntimeError("El alta no respondió 202 con pedidoId")

    print("5. Esperando al Worker mediante polling...")

    consulta_final = None

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
            consulta_final = data
            print(
                f"   Estado={estado}, "
                f"polling={intento}"
            )
            break

        time.sleep(0.5)

    if not consulta_final:
        raise RuntimeError("Timeout esperando estado final")

    resultado["consultaFinal"] = consulta_final

    if consulta_final.get("estado") != "DESPACHADO":
        raise RuntimeError(
            f'Estado final inesperado: '
            f'{consulta_final.get("estado")}'
        )

    print("6. Validando montos...")

    subtotal = consulta_final.get("subtotal")
    envio = consulta_final.get("envio")
    total = consulta_final.get("total")

    print(
        f"   subtotal={subtotal}, "
        f"envio={envio}, "
        f"total={total}"
    )

    montos_ok = (
        float(subtotal) == 11.0
        and float(envio) == 8.0
        and float(total) == 19.0
    )

    if not montos_ok:
        raise RuntimeError(
            f"Montos inesperados: "
            f"subtotal={subtotal}, envio={envio}, total={total}"
        )

    print("7. Validando MongoDB...")

    mongo_final = mongo(f"""
const p = db.Pedido.findOne({{_id:"{pedido_id}"}});

const s = db.Stock.findOne({{
    IdProducto:"SKU-00002",
    IdAlmacen:"ALM-01"
}});

print(JSON.stringify({{
    estado:p?.IdEstado,
    reservarStock:db.PedidoProceso.countDocuments({{
        IdPedido:"{pedido_id}",
        Paso:"RESERVAR_STOCK"
    }}),
    calcularEnvio:db.PedidoProceso.countDocuments({{
        IdPedido:"{pedido_id}",
        Paso:"CALCULAR_ENVIO"
    }}),
    generarGuia:db.PedidoProceso.countDocuments({{
        IdPedido:"{pedido_id}",
        Paso:"GENERAR_GUIA"
    }}),
    confirmarDespacho:db.PedidoProceso.countDocuments({{
        IdPedido:"{pedido_id}",
        Paso:"CONFIRMAR_DESPACHO"
    }}),
    guias:db.Guia.countDocuments({{
        IdPedido:"{pedido_id}"
    }}),
    disponible:s?.CantidadStock,
    reservado:s?.ReservaStock
}}));
""")

    resultado["mongo"] = mongo_final

    print(json.dumps(mongo_final, indent=2))

    mongo_ok = (
        mongo_final["estado"] == "DESPACHADO"
        and mongo_final["reservarStock"] == 1
        and mongo_final["calcularEnvio"] == 1
        and mongo_final["generarGuia"] == 1
        and mongo_final["confirmarDespacho"] == 1
        and mongo_final["guias"] == 1
        and mongo_final["disponible"] == 19
        and mongo_final["reservado"] == 0
    )

    if not mongo_ok:
        raise RuntimeError("Validación Mongo incorrecta")

    print("8. Validando transportista...")

    status_t, trans = http(
        f"{TRANSPORTISTA}/guias?"
        f"pedidoId={urllib.parse.quote(pedido_id)}"
    )

    guias = trans.get("guias", []) if status_t == 200 else []
    activas = [g for g in guias if g.get("estado") == "ACTIVA"]

    resultado["transportista"] = {
        "http": status_t,
        "cantidad": len(guias),
        "activas": len(activas),
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
        raise RuntimeError("Transportista no tiene exactamente 1 guía activa")

    resultado["resultado"] = "PASS"

    print()
    print("✅ E2E 01: PASS")

except Exception as e:
    resultado["error"] = str(e)
    print()
    print(f"❌ E2E 01: FAIL - {e}")

with open(EVIDENCIA, "w", encoding="utf-8") as f:
    json.dump(resultado, f, ensure_ascii=False, indent=2)

print(f"Evidencia JSON: {EVIDENCIA}")

raise SystemExit(0 if resultado["resultado"] == "PASS" else 1)
