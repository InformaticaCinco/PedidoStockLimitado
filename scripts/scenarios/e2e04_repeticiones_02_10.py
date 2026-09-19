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

TIMEOUT_PROCESO = 90
POLL_SECONDS = 0.5

EVIDENCE_DIR = os.path.join("tests", "evidencias")
EVIDENCE_JSON = os.path.join(
    EVIDENCE_DIR,
    "e2e04-repeticiones-02-10.json"
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

    lineas = [x.strip() for x in out.splitlines() if x.strip()]

    if not lineas:
        raise RuntimeError("Mongo no devolvió información")

    return json.loads(lineas[-1])


def request_json(url, method="GET", body=None, token=None, timeout=20):
    data = None if body is None else json.dumps(body).encode("utf-8")

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
        with urllib.request.urlopen(req, timeout=timeout) as r:
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
    IdProducto: "SKU-00001",
    IdAlmacen: "ALM-01"
});

print(JSON.stringify({
    disponible: s?.CantidadStock ?? null,
    reservado: s?.ReservaStock ?? null,
    total: (s?.CantidadStock ?? 0) + (s?.ReservaStock ?? 0)
}));
""")


def snapshot(prefix):
    return mongo_eval(f"""
const pedidos = db.Pedido.find({{
    IdSolicitud: /^${prefix}/
}}).toArray();

const porEstado = {{}};

for (const p of pedidos) {{
    porEstado[p.IdEstado] = (porEstado[p.IdEstado] || 0) + 1;
}}

const s = db.Stock.findOne({{
    IdProducto: "SKU-00001",
    IdAlmacen: "ALM-01"
}});

print(JSON.stringify({{
    totalPedidos: pedidos.length,
    porEstado: porEstado,
    disponible: s?.CantidadStock ?? null,
    reservado: s?.ReservaStock ?? null
}}));
""".replace("/^$", "/^"))


def final_detail(prefix):
    return mongo_eval(f"""
const pedidos = db.Pedido.find({{
    IdSolicitud: /^{prefix}/
}}).toArray();

const ids = pedidos.map(p => p._id);

const despachados = pedidos
    .filter(p => p.IdEstado === "DESPACHADO")
    .map(p => p._id);

const anulados = pedidos
    .filter(p => p.IdEstado === "ANULADO")
    .map(p => p._id);

const porEstado = {{}};

for (const p of pedidos) {{
    porEstado[p.IdEstado] = (porEstado[p.IdEstado] || 0) + 1;
}}

const reservaPorEstado = {{}};

for (const p of db.PedidoProceso.find({{
    IdPedido: {{$in: ids}},
    Paso: "RESERVAR_STOCK"
}}).toArray()) {{
    reservaPorEstado[p.IdEstadoProceso] =
        (reservaPorEstado[p.IdEstadoProceso] || 0) + 1;
}}

const stock = db.Stock.findOne({{
    IdProducto: "SKU-00001",
    IdAlmacen: "ALM-01"
}});

print(JSON.stringify({{
    totalPedidos: pedidos.length,
    porEstado: porEstado,

    stockDisponible: stock?.CantidadStock ?? null,
    stockReservado: stock?.ReservaStock ?? null,
    stockTotal:
        (stock?.CantidadStock ?? 0) +
        (stock?.ReservaStock ?? 0),

    procesosGenerarGuiaOK:
        db.PedidoProceso.countDocuments({{
            IdPedido: {{$in: ids}},
            Paso: "GENERAR_GUIA",
            IdEstadoProceso: "OK"
        }}),

    guiasTotales:
        db.Guia.countDocuments({{
            IdPedido: {{$in: ids}}
        }}),

    guiasDespachados:
        db.Guia.countDocuments({{
            IdPedido: {{$in: despachados}}
        }}),

    guiasAnulados:
        db.Guia.countDocuments({{
            IdPedido: {{$in: anulados}}
        }}),

    reservaPorEstado: reservaPorEstado,
    despachadosIds: despachados
}}));
""")


def login_40():
    tokens = {}

    for i in range(1, 41):
        usuario = f"comprador{i:02d}"

        status, response = request_json(
            f"{BASE}/auth/login",
            method="POST",
            body={
                "usuario": usuario,
                "clave": PASSWORD
            }
        )

        if status != 200:
            raise RuntimeError(
                f"Login falló para {usuario}: "
                f"HTTP {status} {response}"
            )

        tokens[i] = response["data"]["accessToken"]

    return tokens


def crear_40(tokens, repeticion):
    barrera = threading.Barrier(40)

    def crear(i):
        solicitud = f"E2E04-R{repeticion:02d}-{i:02d}"

        body = {
            "solicitudId": solicitud,
            "almacenId": "ALM-01",
            "zonaEntrega": "LIMA_METROPOLITANA",
            "items": [
                {
                    "sku": "SKU-00001",
                    "cantidad": 1
                }
            ]
        }

        barrera.wait()

        status, response = request_json(
            f"{BASE}/pedidos",
            method="POST",
            body=body,
            token=tokens[i]
        )

        pedido_id = None

        if isinstance(response, dict):
            pedido_id = (response.get("data") or {}).get("pedidoId")

        return {
            "comprador": f"comprador{i:02d}",
            "solicitudId": solicitud,
            "http": status,
            "pedidoId": pedido_id
        }

    resultados = []

    with ThreadPoolExecutor(max_workers=40) as pool:
        futures = [
            pool.submit(crear, i)
            for i in range(1, 41)
        ]

        for future in as_completed(futures):
            resultados.append(future.result())

    return sorted(
        resultados,
        key=lambda x: x["solicitudId"]
    )


def esperar_final(prefix):
    inicio = time.time()

    min_disponible = None
    min_reservado = None
    muestras = 0
    ultimo = None

    terminales = {
        "DESPACHADO",
        "ANULADO",
        "REQUIERE_REVISION"
    }

    while time.time() - inicio < TIMEOUT_PROCESO:
        ultimo = snapshot(prefix)
        muestras += 1

        disponible = ultimo["disponible"]
        reservado = ultimo["reservado"]

        if disponible is not None:
            min_disponible = (
                disponible
                if min_disponible is None
                else min(min_disponible, disponible)
            )

        if reservado is not None:
            min_reservado = (
                reservado
                if min_reservado is None
                else min(min_reservado, reservado)
            )

        estados = ultimo.get("porEstado", {})

        total_final = sum(
            estados.get(x, 0)
            for x in terminales
        )

        if (
            ultimo.get("totalPedidos") == 40
            and total_final == 40
        ):
            return {
                "snapshot": ultimo,
                "muestras": muestras,
                "minDisponibleObservado": min_disponible,
                "minReservadoObservado": min_reservado,
                "segundos": round(time.time() - inicio, 2)
            }

        time.sleep(POLL_SECONDS)

    raise RuntimeError(
        f"Timeout esperando estados finales. Último estado: {ultimo}"
    )


def validar_transportista(ids):
    detalle = []
    correctas = 0

    for pedido_id in ids:
        url = (
            f"{TRANSPORTISTA}/guias?"
            f"pedidoId={urllib.parse.quote(pedido_id)}"
        )

        status, payload = request_json(url)

        activas = []

        if status == 200 and isinstance(payload, dict):
            activas = [
                g for g in payload.get("guias", [])
                if g.get("estado") == "ACTIVA"
            ]

        ok = status == 200 and len(activas) == 1

        if ok:
            correctas += 1

        detalle.append({
            "pedidoId": pedido_id,
            "http": status,
            "guiasActivas": len(activas),
            "ok": ok
        })

    return correctas, detalle


resultados_globales = []

print("==================================================")
print("E2E 04 - REPETICIONES AUTOMATIZADAS 02 A 10")
print("==================================================")
print("R01 ya fue validada manualmente: OK")
print()

for repeticion in range(2, 11):
    print(f"---------- REPETICION {repeticion}/10 ----------")

    resultado = {
        "repeticion": repeticion,
        "resultado": "FAIL"
    }

    inicio_rep = time.time()

    try:
        print("1. Restableciendo entorno limpio...")

        run_cmd([
            "docker", "compose",
            "down", "-v"
        ])

        run_cmd([
            "docker", "compose",
            "up", "-d",
            "--no-build",
            "--wait",
            "--wait-timeout", "240"
        ])

        print("   Docker Compose: OK")

        print("2. Validando stock inicial...")

        baseline = baseline_stock()
        resultado["baseline"] = baseline

        baseline_ok = (
            baseline["disponible"] == 3
            and baseline["reservado"] == 0
            and baseline["total"] == 3
        )

        print(
            f'   Stock inicial: '
            f'{baseline["disponible"]}/'
            f'{baseline["reservado"]}/'
            f'{baseline["total"]}'
        )

        if not baseline_ok:
            raise RuntimeError(
                f"Baseline incorrecto: {baseline}"
            )

        print("3. Login de comprador01 a comprador40...")

        tokens = login_40()

        print("   Logins: 40/40 OK")

        print("4. Lanzando 40 pedidos simultáneos...")

        creaciones = crear_40(tokens, repeticion)

        http_202 = sum(
            1 for x in creaciones
            if x["http"] == 202
        )

        ids_unicos = len({
            x["pedidoId"]
            for x in creaciones
            if x["pedidoId"]
        })

        resultado["creacion"] = {
            "total": len(creaciones),
            "http202": http_202,
            "pedidoIdUnicos": ids_unicos
        }

        print(
            f"   Total={len(creaciones)}, "
            f"HTTP202={http_202}, "
            f"IDs únicos={ids_unicos}"
        )

        if not (
            len(creaciones) == 40
            and http_202 == 40
            and ids_unicos == 40
        ):
            raise RuntimeError(
                "La creación concurrente no produjo "
                "40 respuestas 202 / 40 IDs únicos"
            )

        prefix = f"E2E04-R{repeticion:02d}-"

        print("5. Esperando al Worker mediante polling...")

        polling = esperar_final(prefix)

        resultado["polling"] = polling

        print(
            f'   Finalizó en {polling["segundos"]} s '
            f'con {polling["muestras"]} consultas'
        )

        print("6. Validando MongoDB...")

        final = final_detail(prefix)
        resultado["final"] = final

        estados = final["porEstado"]

        print(
            f'   DESPACHADO={estados.get("DESPACHADO", 0)}, '
            f'ANULADO={estados.get("ANULADO", 0)}'
        )

        print(
            f'   Stock final='
            f'{final["stockDisponible"]}/'
            f'{final["stockReservado"]}'
        )

        print(
            f'   Guías Mongo='
            f'{final["guiasTotales"]}'
        )

        print("7. Validando simulador del transportista...")

        transportista_ok, transportista_detalle = (
            validar_transportista(
                final["despachadosIds"]
            )
        )

        resultado["transportista"] = {
            "pedidosConUnaGuiaActiva": transportista_ok,
            "detalle": transportista_detalle
        }

        print(
            f"   Guías activas correctas: "
            f"{transportista_ok}/3"
        )

        estados_ok = (
            estados.get("DESPACHADO", 0) == 3
            and estados.get("ANULADO", 0) == 37
            and sum(estados.values()) == 40
        )

        stock_ok = (
            final["stockDisponible"] == 0
            and final["stockReservado"] == 0
            and final["stockTotal"] == 0
        )

        guias_ok = (
            final["procesosGenerarGuiaOK"] == 3
            and final["guiasTotales"] == 3
            and final["guiasDespachados"] == 3
            and final["guiasAnulados"] == 0
            and transportista_ok == 3
        )

        nunca_negativo = (
            polling["minDisponibleObservado"] is not None
            and polling["minDisponibleObservado"] >= 0
            and polling["minReservadoObservado"] is not None
            and polling["minReservadoObservado"] >= 0
        )

        resultado["validaciones"] = {
            "estados": estados_ok,
            "stock": stock_ok,
            "guias": guias_ok,
            "nuncaNegativoObservado": nunca_negativo
        }

        if (
            estados_ok
            and stock_ok
            and guias_ok
            and nunca_negativo
        ):
            resultado["resultado"] = "PASS"
            print(
                f"✅ REPETICION {repeticion}/10: PASS"
            )
        else:
            raise RuntimeError(
                "Alguna validación final no coincide: "
                f"{resultado['validaciones']}"
            )

    except Exception as e:
        resultado["error"] = str(e)
        resultado["resultado"] = "FAIL"

        print(
            f"❌ REPETICION {repeticion}/10: FAIL"
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
                "escenario": "E2E 04 - Ultimas unidades",
                "repeticion01": {
                    "resultado": "PASS",
                    "tipo": "validacion manual previa"
                },
                "repeticiones02a10": resultados_globales
            },
            f,
            ensure_ascii=False,
            indent=2
        )

    print()


passes = sum(
    1 for r in resultados_globales
    if r["resultado"] == "PASS"
)

fails = len(resultados_globales) - passes

print("==================================================")
print("RESUMEN E2E 04")
print("==================================================")
print("Repetición 01/10: PASS (manual)")
print(f"Repeticiones 02-10 PASS: {passes}/9")
print(f"Repeticiones 02-10 FAIL: {fails}/9")
print(f"Evidencia JSON: {EVIDENCE_JSON}")

if fails == 0:
    print()
    print("✅ E2E 04 COMPLETO: 10/10 REPETICIONES OK")
else:
    print()
    print("❌ E2E 04 NO PUEDE CERRARSE TODAVÍA")

raise SystemExit(0 if fails == 0 else 1)
