import json
import os
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE = "http://localhost:8080/api/java"
TRANSPORTISTA = "http://localhost:9090"
PASSWORD = "Reto2026!"
MONGO_URI = "mongodb://localhost:27017/pedidos_stock?directConnection=true"

TIMEOUT_PROCESO = 60
POLL_SECONDS = 0.5

EVIDENCE_DIR = os.path.join("tests", "evidencias")
EVIDENCE_JSON = os.path.join(
    EVIDENCE_DIR,
    "e2e05-repeticiones-02-10.json"
)

os.makedirs(EVIDENCE_DIR, exist_ok=True)


def run_cmd(args):
    p = subprocess.run(
        args,
        text=True,
        capture_output=True
    )

    if p.returncode != 0:
        raise RuntimeError(
            f"Comando falló: {' '.join(args)}\n"
            f"STDOUT:\n{p.stdout}\n"
            f"STDERR:\n{p.stderr}"
        )

    return p.stdout.strip()


def mongo_eval(js):
    out = run_cmd([
        "docker", "compose", "exec", "-T",
        "mongodb",
        "mongosh",
        "--quiet",
        MONGO_URI,
        "--eval",
        js
    ])

    lineas = [
        x.strip()
        for x in out.splitlines()
        if x.strip()
    ]

    if not lineas:
        raise RuntimeError("Mongo no devolvió información")

    return json.loads(lineas[-1])


def request_json(
    url,
    method="GET",
    body=None,
    token=None,
    timeout=20
):
    data = (
        None
        if body is None
        else json.dumps(body).encode("utf-8")
    )

    headers = {
        "Content-Type": "application/json"
    }

    if token:
        headers["Authorization"] = f"Bearer {token}"

    req = urllib.request.Request(
        url,
        data=data,
        headers=headers,
        method=method
    )

    try:
        with urllib.request.urlopen(
            req,
            timeout=timeout
        ) as r:
            raw = r.read().decode("utf-8")

            try:
                payload = json.loads(raw)
            except Exception:
                payload = {"raw": raw}

            return r.status, payload

    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8")

        try:
            payload = json.loads(raw)
        except Exception:
            payload = {"raw": raw}

        return e.code, payload

    except Exception as e:
        return 0, {"error": str(e)}


def baseline_stock():
    return mongo_eval("""
const s = db.Stock.findOne({
    IdProducto: "SKU-00002",
    IdAlmacen: "ALM-01"
});

print(JSON.stringify({
    disponible: s?.CantidadStock ?? null,
    reservado: s?.ReservaStock ?? null,
    total:
        (s?.CantidadStock ?? 0) +
        (s?.ReservaStock ?? 0)
}));
""")


def login():
    status, response = request_json(
        f"{BASE}/auth/login",
        method="POST",
        body={
            "usuario": "comprador01",
            "clave": PASSWORD
        }
    )

    if status != 200:
        raise RuntimeError(
            f"Login falló: HTTP {status} {response}"
        )

    return response["data"]["accessToken"]


def crear_40_identicos(token, repeticion):
    barrera = threading.Barrier(40)

    solicitud_id = (
        f"E2E05-R{repeticion:02d}-001"
    )

    body = {
        "solicitudId": solicitud_id,
        "almacenId": "ALM-01",
        "zonaEntrega": "LIMA_METROPOLITANA",
        "items": [
            {
                "sku": "SKU-00002",
                "cantidad": 1
            }
        ]
    }

    def enviar(numero):
        barrera.wait()

        status, response = request_json(
            f"{BASE}/pedidos",
            method="POST",
            body=body,
            token=token
        )

        data = (
            response.get("data") or {}
            if isinstance(response, dict)
            else {}
        )

        return {
            "numero": numero,
            "http": status,
            "pedidoId": data.get("pedidoId"),
            "estado": data.get("estado")
        }

    resultados = []

    with ThreadPoolExecutor(max_workers=40) as pool:
        futures = [
            pool.submit(enviar, i)
            for i in range(1, 41)
        ]

        for future in as_completed(futures):
            resultados.append(future.result())

    resultados.sort(
        key=lambda x: x["numero"]
    )

    return solicitud_id, resultados


def esperar_estado_final(pedido_id, token):
    terminales = {
        "DESPACHADO",
        "ANULADO",
        "REQUIERE_REVISION"
    }

    inicio = time.time()
    muestras = []

    while time.time() - inicio < TIMEOUT_PROCESO:
        status, response = request_json(
            f"{BASE}/pedidos/{pedido_id}",
            token=token
        )

        data = (
            response.get("data") or {}
            if isinstance(response, dict)
            else {}
        )

        estado = data.get("estado")

        muestras.append({
            "http": status,
            "estado": estado
        })

        if status == 200 and estado in terminales:
            return {
                "estadoFinal": estado,
                "muestras": len(muestras),
                "segundos": round(
                    time.time() - inicio,
                    2
                ),
                "detalle": muestras
            }

        time.sleep(POLL_SECONDS)

    raise RuntimeError(
        f"Timeout esperando pedido {pedido_id}. "
        f"Últimas muestras: {muestras[-5:]}"
    )


def validar_mongo(solicitud_id):
    return mongo_eval(f"""
const solicitudId = "{solicitud_id}";

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

    estadoPedido:
        pedidos.length === 1
            ? pedidos[0].IdEstado
            : null,

    pedidoId:
        pedidos.length === 1
            ? pedidos[0]._id
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

    stockDisponible: stock?.CantidadStock ?? null,
    stockReservado: stock?.ReservaStock ?? null,
    stockTotal:
        (stock?.CantidadStock ?? 0) +
        (stock?.ReservaStock ?? 0)
}}));
""")


def validar_transportista(pedido_id):
    url = (
        f"{TRANSPORTISTA}/guias?"
        f"pedidoId={urllib.parse.quote(pedido_id)}"
    )

    status, response = request_json(url)

    guias = []

    if status == 200 and isinstance(response, dict):
        guias = response.get("guias", [])

    activas = [
        g
        for g in guias
        if g.get("estado") == "ACTIVA"
    ]

    return {
        "http": status,
        "cantidadGuias": len(guias),
        "guiasActivas": len(activas),
        "respuesta": response
    }


resultados_globales = []

print("==================================================")
print("E2E 05 - REPETICIONES AUTOMATIZADAS 02 A 10")
print("==================================================")
print("R01 ya fue validada manualmente: PASS")
print()

for repeticion in range(2, 11):
    print(
        f"---------- REPETICION "
        f"{repeticion}/10 ----------"
    )

    resultado = {
        "repeticion": repeticion,
        "resultado": "FAIL"
    }

    inicio_rep = time.time()

    try:
        print("1. Restableciendo entorno limpio...")

        run_cmd([
            "docker",
            "compose",
            "down",
            "-v"
        ])

        run_cmd([
            "docker",
            "compose",
            "up",
            "-d",
            "--no-build",
            "--wait",
            "--wait-timeout",
            "240"
        ])

        print("   Docker Compose: OK")

        print("2. Validando stock inicial...")

        baseline = baseline_stock()
        resultado["baseline"] = baseline

        print(
            f'   Stock inicial: '
            f'{baseline["disponible"]}/'
            f'{baseline["reservado"]}/'
            f'{baseline["total"]}'
        )

        if not (
            baseline["disponible"] == 20
            and baseline["reservado"] == 0
            and baseline["total"] == 20
        ):
            raise RuntimeError(
                f"Baseline incorrecto: {baseline}"
            )

        print("3. Login comprador01...")

        token = login()

        print("   Login: OK")

        print(
            "4. Lanzando 40 peticiones "
            "simultáneas idénticas..."
        )

        solicitud_id, creaciones = (
            crear_40_identicos(
                token,
                repeticion
            )
        )

        http_202 = sum(
            1 for x in creaciones
            if x["http"] == 202
        )

        http_200 = sum(
            1 for x in creaciones
            if x["http"] == 200
        )

        otros = sum(
            1 for x in creaciones
            if x["http"] not in (200, 202)
        )

        ids = {
            x["pedidoId"]
            for x in creaciones
            if x["pedidoId"]
        }

        resultado["creacion"] = {
            "total": len(creaciones),
            "http202": http_202,
            "http200": http_200,
            "otrosHttp": otros,
            "pedidoIdUnicos": len(ids)
        }

        print(
            f"   Total={len(creaciones)}, "
            f"202={http_202}, "
            f"200={http_200}, "
            f"otros={otros}, "
            f"IDs únicos={len(ids)}"
        )

        if not (
            len(creaciones) == 40
            and http_202 == 1
            and http_200 == 39
            and otros == 0
            and len(ids) == 1
        ):
            raise RuntimeError(
                "Resultado HTTP/idempotencia inesperado"
            )

        pedido_id = next(iter(ids))

        print(
            "5. Esperando estado final "
            "mediante polling por API..."
        )

        polling = esperar_estado_final(
            pedido_id,
            token
        )

        resultado["polling"] = polling

        print(
            f'   Estado={polling["estadoFinal"]}, '
            f'{polling["muestras"]} consulta(s), '
            f'{polling["segundos"]} s'
        )

        if polling["estadoFinal"] != "DESPACHADO":
            raise RuntimeError(
                "El único pedido no terminó DESPACHADO"
            )

        print("6. Validando MongoDB...")

        mongo = validar_mongo(
            solicitud_id
        )

        resultado["mongo"] = mongo

        print(
            f'   Pedidos={mongo["cantidadPedidos"]}, '
            f'guías={mongo["guiasMongo"]}, '
            f'stock='
            f'{mongo["stockDisponible"]}/'
            f'{mongo["stockReservado"]}'
        )

        mongo_ok = (
            mongo["cantidadPedidos"] == 1
            and mongo["estadoPedido"] == "DESPACHADO"
            and mongo["pedidoId"] == pedido_id
            and mongo["reservarStock"] == 1
            and mongo["calcularEnvio"] == 1
            and mongo["generarGuia"] == 1
            and mongo["confirmarDespacho"] == 1
            and mongo["guiasMongo"] == 1
            and mongo["stockDisponible"] == 19
            and mongo["stockReservado"] == 0
            and mongo["stockTotal"] == 19
        )

        print(
            "7. Validando simulador "
            "del transportista..."
        )

        transportista = validar_transportista(
            pedido_id
        )

        resultado["transportista"] = transportista

        print(
            f'   Guías={transportista["cantidadGuias"]}, '
            f'activas={transportista["guiasActivas"]}'
        )

        transportista_ok = (
            transportista["http"] == 200
            and transportista["cantidadGuias"] == 1
            and transportista["guiasActivas"] == 1
        )

        resultado["validaciones"] = {
            "httpIdempotencia": True,
            "estadoFinal": True,
            "mongo": mongo_ok,
            "transportista": transportista_ok
        }

        if mongo_ok and transportista_ok:
            resultado["resultado"] = "PASS"

            print(
                f"✅ REPETICION "
                f"{repeticion}/10: PASS"
            )

        else:
            raise RuntimeError(
                "Alguna validación final falló: "
                f"{resultado['validaciones']}"
            )

    except Exception as e:
        resultado["resultado"] = "FAIL"
        resultado["error"] = str(e)

        print(
            f"❌ REPETICION "
            f"{repeticion}/10: FAIL"
        )
        print(f"   {e}")

    resultado["duracionSegundos"] = round(
        time.time() - inicio_rep,
        2
    )

    resultados_globales.append(resultado)

    with open(
        EVIDENCE_JSON,
        "w",
        encoding="utf-8"
    ) as f:
        json.dump(
            {
                "escenario":
                    "E2E 05 - "
                    "40 peticiones simultaneas identicas",
                "repeticion01": {
                    "resultado": "PASS",
                    "tipo":
                        "validacion manual previa"
                },
                "repeticiones02a10":
                    resultados_globales
            },
            f,
            ensure_ascii=False,
            indent=2
        )

    print()


passes = sum(
    1
    for r in resultados_globales
    if r["resultado"] == "PASS"
)

fails = len(resultados_globales) - passes

print("==================================================")
print("RESUMEN E2E 05")
print("==================================================")
print("Repetición 01/10: PASS (manual)")
print(f"Repeticiones 02-10 PASS: {passes}/9")
print(f"Repeticiones 02-10 FAIL: {fails}/9")
print(f"Evidencia JSON: {EVIDENCE_JSON}")

if fails == 0:
    print()
    print(
        "✅ E2E 05 COMPLETO: "
        "10/10 REPETICIONES OK"
    )
else:
    print()
    print(
        "❌ E2E 05 NO PUEDE "
        "CERRARSE TODAVÍA"
    )

raise SystemExit(
    0 if fails == 0 else 1
)
