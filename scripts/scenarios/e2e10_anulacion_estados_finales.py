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

EVIDENCIA = "tests/evidencias/e2e10-anulacion-estados-finales.json"

os.makedirs("tests/evidencias", exist_ok=True)


def cmd(args):
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


def esperar_final(pedido_id, token):
    terminales = {
        "DESPACHADO",
        "ANULADO",
        "REQUIERE_REVISION"
    }

    for intento in range(1, 121):
        status, response = http(
            f"{BASE}/pedidos/{pedido_id}",
            token=token
        )

        data = response.get("data") or {}
        estado = data.get("estado")

        if status == 200 and estado in terminales:
            return estado, intento, data

        time.sleep(0.5)

    raise RuntimeError(
        f"Timeout esperando estado final de {pedido_id}"
    )


resultado = {
    "escenario":
        "E2E 10 - Anulacion de estados finales",
    "resultado": "FAIL"
}


try:
    print("1. Restableciendo entorno limpio...")

    cmd([
        "docker", "compose",
        "down", "-v", "--remove-orphans"
    ])

    env = os.environ.copy()
    env["FAILURE_RATE"] = "0"
    env["PARTIAL_RATE"] = "0"

    p = subprocess.run(
        [
            "docker", "compose",
            "up", "-d",
            "--no-build",
            "--wait",
            "--wait-timeout", "240"
        ],
        text=True,
        capture_output=True,
        env=env
    )

    if p.returncode != 0:
        raise RuntimeError(
            f"Docker Compose falló:\n"
            f"{p.stdout}\n{p.stderr}"
        )

    print("   Docker Compose: OK")

    print("2. Login comprador01...")

    status_login, login = http(
        f"{BASE}/auth/login",
        "POST",
        {
            "usuario": "comprador01",
            "clave": "Reto2026!"
        }
    )

    if status_login != 200:
        raise RuntimeError(
            f"Login HTTP {status_login}: {login}"
        )

    token = login["data"]["accessToken"]

    # =====================================================
    # CASO A
    # =====================================================

    print()
    print("=== CASO A: ANULAR PEDIDO DESPACHADO ===")

    print("3. Creando pedido que debe despacharse...")

    status_a, alta_a = http(
        f"{BASE}/pedidos",
        "POST",
        {
            "solicitudId":
                "E2E10-DESPACHADO-001",
            "almacenId":
                "ALM-01",
            "zonaEntrega":
                "LIMA_METROPOLITANA",
            "items": [
                {
                    "sku": "SKU-00002",
                    "cantidad": 1
                }
            ]
        },
        token
    )

    pedido_a = (
        (alta_a.get("data") or {}).get("pedidoId")
    )

    print(
        f"   HTTP={status_a}, "
        f"pedidoId={pedido_a}"
    )

    if status_a != 202 or not pedido_a:
        raise RuntimeError(
            "No se pudo crear el pedido A"
        )

    print("4. Esperando DESPACHADO...")

    estado_a, polling_a, detalle_a = esperar_final(
        pedido_a,
        token
    )

    print(
        f"   Estado={estado_a}, "
        f"polling={polling_a}"
    )

    if estado_a != "DESPACHADO":
        raise RuntimeError(
            f"Pedido A debía quedar DESPACHADO, "
            f"quedó {estado_a}"
        )

    print(
        "5. Intentando anular pedido "
        "ya DESPACHADO..."
    )

    status_anula_a, resp_anula_a = http(
        f"{BASE}/pedidos/{pedido_a}/anulacion",
        "POST",
        token=token
    )

    print(
        f"   HTTP={status_anula_a}, "
        f'message={resp_anula_a.get("message")}'
    )

    if status_anula_a != 409:
        raise RuntimeError(
            f"Se esperaba 409, "
            f"se obtuvo {status_anula_a}"
        )

    print(
        "6. Verificando que el pedido "
        "despachado no cambió..."
    )

    validacion_a = mongo(f"""
const p = db.Pedido.findOne({{
    _id:"{pedido_a}"
}});

const s = db.Stock.findOne({{
    IdProducto:"SKU-00002",
    IdAlmacen:"ALM-01"
}});

print(JSON.stringify({{
    estado:p?.IdEstado ?? null,
    stockDisponible:s?.CantidadStock ?? null,
    stockReservado:s?.ReservaStock ?? null,
    guias:db.Guia.countDocuments({{
        IdPedido:"{pedido_a}"
    }})
}}));
""")

    print(json.dumps(
        validacion_a,
        indent=2,
        ensure_ascii=False
    ))

    if not (
        validacion_a["estado"] == "DESPACHADO"
        and validacion_a["stockDisponible"] == 19
        and validacion_a["stockReservado"] == 0
        and validacion_a["guias"] == 1
    ):
        raise RuntimeError(
            "El 409 alteró el pedido despachado"
        )

    status_t, trans_a = http(
        f"{TRANSPORTISTA}/guias?"
        f"pedidoId={urllib.parse.quote(pedido_a)}"
    )

    guias_a = (
        trans_a.get("guias", [])
        if status_t == 200
        else []
    )

    activas_a = [
        g for g in guias_a
        if g.get("estado") == "ACTIVA"
    ]

    if not (
        status_t == 200
        and len(activas_a) == 1
    ):
        raise RuntimeError(
            "La guía del pedido despachado "
            "no quedó activa"
        )

    resultado["pedidoDespachado"] = {
        "pedidoId": pedido_a,
        "estadoAntes": estado_a,
        "anulacionHttp": status_anula_a,
        "respuestaAnulacion": resp_anula_a,
        "mongo": validacion_a,
        "guiasActivas": len(activas_a)
    }

    # =====================================================
    # CASO B
    # =====================================================

    print()
    print("=== CASO B: ANULACION REPETIDA DE ANULADO ===")

    print(
        "7. Creando pedido que será "
        "ANULADO por falta de stock..."
    )

    status_b, alta_b = http(
        f"{BASE}/pedidos",
        "POST",
        {
            "solicitudId":
                "E2E10-ANULADO-001",
            "almacenId":
                "ALM-01",
            "zonaEntrega":
                "LIMA_METROPOLITANA",
            "items": [
                {
                    "sku": "SKU-00001",
                    "cantidad": 4
                }
            ]
        },
        token
    )

    pedido_b = (
        (alta_b.get("data") or {}).get("pedidoId")
    )

    print(
        f"   HTTP={status_b}, "
        f"pedidoId={pedido_b}"
    )

    if status_b != 202 or not pedido_b:
        raise RuntimeError(
            "No se pudo crear el pedido B"
        )

    print("8. Esperando ANULADO...")

    estado_b, polling_b, detalle_b = esperar_final(
        pedido_b,
        token
    )

    print(
        f"   Estado={estado_b}, "
        f"polling={polling_b}"
    )

    if estado_b != "ANULADO":
        raise RuntimeError(
            f"Pedido B debía quedar ANULADO, "
            f"quedó {estado_b}"
        )

    print(
        "9. Solicitando anulación "
        "sobre pedido ya ANULADO..."
    )

    status_b1, resp_b1 = http(
        f"{BASE}/pedidos/{pedido_b}/anulacion",
        "POST",
        token=token
    )

    print(
        f"   Primera repetición: "
        f"HTTP={status_b1}, "
        f'message={resp_b1.get("message")}'
    )

    if status_b1 != 200:
        raise RuntimeError(
            f"Se esperaba 200, "
            f"se obtuvo {status_b1}"
        )

    print("10. Repitiendo nuevamente la anulación...")

    status_b2, resp_b2 = http(
        f"{BASE}/pedidos/{pedido_b}/anulacion",
        "POST",
        token=token
    )

    print(
        f"   Segunda repetición: "
        f"HTTP={status_b2}, "
        f'message={resp_b2.get("message")}'
    )

    if status_b2 != 200:
        raise RuntimeError(
            f"Se esperaba 200 repetido, "
            f"se obtuvo {status_b2}"
        )

    print(
        "11. Verificando ausencia "
        "de efectos adicionales..."
    )

    validacion_b = mongo(f"""
const p = db.Pedido.findOne({{
    _id:"{pedido_b}"
}});

const s = db.Stock.findOne({{
    IdProducto:"SKU-00001",
    IdAlmacen:"ALM-01"
}});

print(JSON.stringify({{
    estado:p?.IdEstado ?? null,
    stockDisponible:s?.CantidadStock ?? null,
    stockReservado:s?.ReservaStock ?? null,
    guias:db.Guia.countDocuments({{
        IdPedido:"{pedido_b}"
    }}),
    generarGuia:
        db.PedidoProceso.countDocuments({{
            IdPedido:"{pedido_b}",
            Paso:"GENERAR_GUIA"
        }})
}}));
""")

    print(json.dumps(
        validacion_b,
        indent=2,
        ensure_ascii=False
    ))

    if not (
        validacion_b["estado"] == "ANULADO"
        and validacion_b["stockDisponible"] == 3
        and validacion_b["stockReservado"] == 0
        and validacion_b["guias"] == 0
        and validacion_b["generarGuia"] == 0
    ):
        raise RuntimeError(
            "La anulación repetida produjo "
            "efectos adicionales"
        )

    resultado["pedidoAnulado"] = {
        "pedidoId": pedido_b,
        "estadoAntes": estado_b,
        "primeraAnulacionHttp": status_b1,
        "segundaAnulacionHttp": status_b2,
        "mongo": validacion_b
    }

    resultado["validaciones"] = {
        "despachadoDevuelve409": True,
        "despachadoNoCambia": True,
        "anuladoDevuelve200": True,
        "anulacionRepetidaDevuelve200": True,
        "anulacionRepetidaSinEfectos": True
    }

    resultado["resultado"] = "PASS"

    print()
    print("✅ E2E 10: PASS")

except Exception as e:
    resultado["error"] = str(e)

    print()
    print(f"❌ E2E 10: FAIL - {e}")


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

print(
    f"Evidencia JSON: {EVIDENCIA}"
)

raise SystemExit(
    0
    if resultado["resultado"] == "PASS"
    else 1
)
