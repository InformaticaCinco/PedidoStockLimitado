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
EVIDENCIA = "tests/evidencias/e2e02-idempotencia-tres-envios.json"

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
    "escenario": "E2E 02 - Misma solicitudId enviada 3 veces",
    "resultado": "FAIL"
}

try:
    print("1. Restableciendo entorno limpio...")

    cmd([
        "docker", "compose",
        "down", "-v"
    ])

    cmd([
        "docker", "compose",
        "up", "-d",
        "--no-build",
        "--wait",
        "--wait-timeout", "240"
    ])

    print("   Docker Compose: OK")

    print("2. Validando stock inicial SKU-00002...")

    inicial = mongo("""
const s = db.Stock.findOne({
    IdProducto: "SKU-00002",
    IdAlmacen: "ALM-01"
});

print(JSON.stringify({
    disponible: s?.CantidadStock ?? null,
    reservado: s?.ReservaStock ?? null
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
            f"Stock inicial incorrecto: {inicial}"
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

    body = {
        "solicitudId": "E2E02-IDEMPOTENCIA-001",
        "almacenId": "ALM-01",
        "zonaEntrega": "LIMA_METROPOLITANA",
        "items": [
            {
                "sku": "SKU-00002",
                "cantidad": 1
            }
        ]
    }

    print("4. Enviando exactamente el mismo pedido 3 veces...")

    respuestas = []

    for numero in range(1, 4):
        status, response = http(
            f"{BASE}/pedidos",
            "POST",
            body,
            token
        )

        data = response.get("data") or {}

        item = {
            "envio": numero,
            "http": status,
            "pedidoId": data.get("pedidoId"),
            "estado": data.get("estado")
        }

        respuestas.append(item)

        print(
            f'   Envío {numero}: '
            f'HTTP={status}, '
            f'pedidoId={item["pedidoId"]}, '
            f'estado={item["estado"]}'
        )

    resultado["respuestas"] = respuestas

    codigos = [x["http"] for x in respuestas]

    ids = {
        x["pedidoId"]
        for x in respuestas
        if x["pedidoId"]
    }

    if codigos != [202, 200, 200]:
        raise RuntimeError(
            f"Códigos HTTP inesperados: {codigos}"
        )

    if len(ids) != 1:
        raise RuntimeError(
            f"Se obtuvieron {len(ids)} pedidoId distintos"
        )

    pedido_id = next(iter(ids))

    print("5. Esperando estado final mediante polling...")

    estado_final = None
    polling = 0

    for intento in range(1, 121):
        status_get, response_get = http(
            f"{BASE}/pedidos/{pedido_id}",
            token=token
        )

        data_get = response_get.get("data") or {}
        estado = data_get.get("estado")

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

    if estado_final != "DESPACHADO":
        raise RuntimeError(
            f"Estado final inesperado: {estado_final}"
        )

    print("6. Validando MongoDB...")

    mongo_final = mongo(f"""
const solicitudId = "E2E02-IDEMPOTENCIA-001";

const pedidos = db.Pedido.find({{
    IdSolicitud: solicitudId
}}).toArray();

const ids = pedidos.map(p => p._id);

const stock = db.Stock.findOne({{
    IdProducto: "SKU-00002",
    IdAlmacen: "ALM-01"
}});

print(JSON.stringify({{
    cantidadPedidos: pedidos.length,

    pedidoId:
        pedidos.length === 1
            ? pedidos[0]._id
            : null,

    estadoPedido:
        pedidos.length === 1
            ? pedidos[0].IdEstado
            : null,

    reservarStock:
        db.PedidoProceso.countDocuments({{
            IdPedido: {{$in: ids}},
            Paso: "RESERVAR_STOCK"
        }}),

    calcularEnvio:
        db.PedidoProceso.countDocuments({{
            IdPedido: {{$in: ids}},
            Paso: "CALCULAR_ENVIO"
        }}),

    generarGuia:
        db.PedidoProceso.countDocuments({{
            IdPedido: {{$in: ids}},
            Paso: "GENERAR_GUIA"
        }}),

    confirmarDespacho:
        db.PedidoProceso.countDocuments({{
            IdPedido: {{$in: ids}},
            Paso: "CONFIRMAR_DESPACHO"
        }}),

    guiasMongo:
        db.Guia.countDocuments({{
            IdPedido: {{$in: ids}}
        }}),

    stockDisponible:
        stock?.CantidadStock ?? null,

    stockReservado:
        stock?.ReservaStock ?? null
}}));
""")

    resultado["mongo"] = mongo_final

    print(json.dumps(
        mongo_final,
        indent=2,
        ensure_ascii=False
    ))

    mongo_ok = (
        mongo_final["cantidadPedidos"] == 1
        and mongo_final["pedidoId"] == pedido_id
        and mongo_final["estadoPedido"] == "DESPACHADO"
        and mongo_final["reservarStock"] == 1
        and mongo_final["calcularEnvio"] == 1
        and mongo_final["generarGuia"] == 1
        and mongo_final["confirmarDespacho"] == 1
        and mongo_final["guiasMongo"] == 1
        and mongo_final["stockDisponible"] == 19
        and mongo_final["stockReservado"] == 0
    )

    if not mongo_ok:
        raise RuntimeError(
            "La idempotencia no quedó consistente en MongoDB"
        )

    print("7. Validando transportista...")

    status_t, trans = http(
        f"{TRANSPORTISTA}/guias?"
        f"pedidoId={urllib.parse.quote(pedido_id)}"
    )

    guias = (
        trans.get("guias", [])
        if status_t == 200
        else []
    )

    activas = [
        g
        for g in guias
        if g.get("estado") == "ACTIVA"
    ]

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
        raise RuntimeError(
            "El transportista no tiene exactamente una guía activa"
        )

    resultado["resultado"] = "PASS"

    print()
    print("✅ E2E 02: PASS")

except Exception as e:
    resultado["error"] = str(e)

    print()
    print(f"❌ E2E 02: FAIL - {e}")

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
