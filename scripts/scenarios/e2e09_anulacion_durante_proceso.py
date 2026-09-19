import json
import os
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = "http://localhost:8080/api/java"
PROXY = "http://localhost:19090"
TRANSPORTISTA = "http://localhost:9090"

MONGO_URI = (
    "mongodb://localhost:27017/"
    "pedidos_stock?directConnection=true"
)

COMPOSE = [
    "docker", "compose",
    "-f", "docker-compose.yml",
    "-f", "tests/integration/e2e09-compose.override.yml"
]

EVIDENCIA = (
    "tests/evidencias/"
    "e2e09-anulacion-durante-proceso.json"
)

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
    out = cmd(
        COMPOSE
        + [
            "exec", "-T",
            "mongodb",
            "mongosh",
            "--quiet",
            MONGO_URI,
            "--eval",
            js
        ]
    )

    lineas = [
        x.strip()
        for x in out.splitlines()
        if x.strip()
    ]

    if not lineas:
        raise RuntimeError(
            "Mongo no devolvió información"
        )

    return json.loads(lineas[-1])


def http(
    url,
    method="GET",
    body=None,
    token=None,
    timeout=20
):
    headers = {
        "Content-Type": "application/json"
    }

    if token:
        headers["Authorization"] = (
            f"Bearer {token}"
        )

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


resultado = {
    "escenario":
        "E2E 09 - "
        "Anulacion durante proceso con compensacion",
    "resultado": "FAIL"
}


try:
    print(
        "1. Restableciendo entorno "
        "con proxy controlado..."
    )

    cmd(
        COMPOSE
        + [
            "down",
            "-v",
            "--remove-orphans"
        ]
    )

    compose_env = os.environ.copy()

    compose_env["FAILURE_RATE"] = "0"
    compose_env["PARTIAL_RATE"] = "0"
    compose_env["LATENCY_MS"] = "3000"

    cmd(
        COMPOSE
        + [
            "up",
            "-d",
            "--no-build",
            "--wait",
            "--wait-timeout",
            "240"
        ],
        env=compose_env
    )

    print("   Docker Compose: OK")

    print(
        "2. Verificando que .NET usa "
        "el proxy de integración..."
    )

    base_url_dotnet = cmd(
        COMPOSE
        + [
            "exec", "-T",
            "despachos-dotnet",
            "printenv",
            "TRANSPORTISTA_BASE_URL"
        ]
    )

    print(
        f"   TRANSPORTISTA_BASE_URL="
        f"{base_url_dotnet}"
    )

    if base_url_dotnet != (
        "http://transportista-proxy:19090"
    ):
        raise RuntimeError(
            "despachos-dotnet no está "
            "usando el proxy E2E09"
        )

    print("3. Validando stock inicial...")

    inicial = mongo("""
const s = db.Stock.findOne({
    IdProducto: "SKU-00002",
    IdAlmacen: "ALM-01"
});

print(JSON.stringify({
    disponible:
        s?.CantidadStock ?? null,
    reservado:
        s?.ReservaStock ?? null,
    total:
        (s?.CantidadStock ?? 0)
        + (s?.ReservaStock ?? 0)
}));
""")

    resultado["stockInicial"] = inicial

    print(
        f'   Stock inicial='
        f'{inicial["disponible"]}/'
        f'{inicial["reservado"]}/'
        f'{inicial["total"]}'
    )

    if not (
        inicial["disponible"] == 20
        and inicial["reservado"] == 0
        and inicial["total"] == 20
    ):
        raise RuntimeError(
            f"Baseline incorrecto: {inicial}"
        )

    print("4. Login comprador01...")

    status_login, login = http(
        f"{BASE}/auth/login",
        method="POST",
        body={
            "usuario": "comprador01",
            "clave": "Reto2026!"
        }
    )

    if status_login != 200:
        raise RuntimeError(
            f"Login HTTP {status_login}: "
            f"{login}"
        )

    token = login["data"]["accessToken"]

    print("5. Registrando pedido...")

    status_alta, alta = http(
        f"{BASE}/pedidos",
        method="POST",
        body={
            "solicitudId":
                "E2E09-ANULACION-001",
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
        token=token
    )

    pedido_id = (
        (alta.get("data") or {}).get(
            "pedidoId"
        )
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

    if (
        status_alta != 202
        or not pedido_id
    ):
        raise RuntimeError(
            "El pedido no respondió "
            "202 con pedidoId"
        )

    print(
        "6. Esperando que el "
        "transportista REAL cree la guía..."
    )

    proxy_status = None

    for intento in range(1, 201):
        status_proxy, data_proxy = http(
            f"{PROXY}/test-status",
            timeout=3
        )

        if (
            status_proxy == 200
            and data_proxy.get(
                "guiaCreada"
            ) is True
            and data_proxy.get(
                "pedidoId"
            ) == pedido_id
        ):
            proxy_status = data_proxy
            print(
                f"   Guía creada detectada "
                f"en intento {intento}"
            )
            break

        time.sleep(0.05)

    if proxy_status is None:
        raise RuntimeError(
            "No se detectó la creación "
            "de guía dentro de la ventana"
        )

    resultado["proxyAntesAnulacion"] = (
        proxy_status
    )

    print(
        "7. Solicitando anulación "
        "MIENTRAS la respuesta de guía "
        "sigue retenida..."
    )

    inicio_anulacion = time.time()

    status_anulacion, anulacion = http(
        f"{BASE}/pedidos/"
        f"{pedido_id}/anulacion",
        method="POST",
        token=token
    )

    ms_anulacion = round(
        (
            time.time()
            - inicio_anulacion
        ) * 1000,
        2
    )

    resultado["anulacion"] = {
        "http": status_anulacion,
        "respuesta": anulacion,
        "ms": ms_anulacion
    }

    print(
        f"   HTTP={status_anulacion}, "
        f"tiempo={ms_anulacion}ms, "
        f'message={anulacion.get("message")}'
    )

    if status_anulacion != 202:
        raise RuntimeError(
            "La anulación debía alcanzar "
            "el proceso con HTTP 202; "
            f"obtuvo {status_anulacion}"
        )

    print(
        "8. Esperando estado final "
        "mediante polling..."
    )

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
            "ANULADO",
            "DESPACHADO",
            "REQUIERE_REVISION"
        }:
            estado_final = estado
            detalle_final = data
            polling = intento
            break

        time.sleep(0.5)

    resultado["estadoFinal"] = (
        estado_final
    )

    resultado["detalleFinal"] = (
        detalle_final
    )

    resultado["polling"] = polling

    print(
        f"   Estado={estado_final}, "
        f"polling={polling}"
    )

    if estado_final != "ANULADO":
        raise RuntimeError(
            f"Se esperaba ANULADO, "
            f"se obtuvo {estado_final}"
        )

    print(
        "9. Validando stock, guía "
        "y compensaciones en MongoDB..."
    )

    mongo_final = mongo(f"""
const pedidoId = "{pedido_id}";

const p = db.Pedido.findOne({{
    _id: pedidoId
}});

const s = db.Stock.findOne({{
    IdProducto: "SKU-00002",
    IdAlmacen: "ALM-01"
}});

const guia = db.Guia.findOne({{
    IdPedido: pedidoId
}});

const compensaciones =
    db.PedidoProceso
      .find({{
          IdPedido: pedidoId,
          TipoProceso: "COMPENSACION"
      }})
      .sort({{
          FechaInicio: 1,
          NroIntento: 1
      }})
      .toArray()
      .map(x => ({{
          Paso: x.Paso,
          Estado: x.IdEstadoProceso,
          Intento: x.NroIntento,
          FechaInicio: x.FechaInicio,
          FechaFin: x.FechaFin
      }}));

const procesos =
    db.PedidoProceso
      .find({{
          IdPedido: pedidoId
      }})
      .sort({{
          FechaInicio: 1,
          NroIntento: 1
      }})
      .toArray()
      .map(x => ({{
          TipoProceso: x.TipoProceso,
          Paso: x.Paso,
          Estado: x.IdEstadoProceso,
          Intento: x.NroIntento
      }}));

print(JSON.stringify({{
    estadoPedido:
        p?.IdEstado ?? null,

    anulacionSolicitada:
        p?.AnulacionSolicitada ?? null,

    stockDisponible:
        s?.CantidadStock ?? null,

    stockReservado:
        s?.ReservaStock ?? null,

    stockTotal:
        (s?.CantidadStock ?? 0)
        + (s?.ReservaStock ?? 0),

    cantidadGuiasMongo:
        db.Guia.countDocuments({{
            IdPedido: pedidoId
        }}),

    estadoGuiaMongo:
        guia?.IdEstado ?? null,

    compensaciones:
        compensaciones,

    procesos:
        procesos
}}));
""")

    resultado["mongo"] = mongo_final

    print(
        json.dumps(
            mongo_final,
            indent=2,
            ensure_ascii=False
        )
    )

    if not (
        mongo_final[
            "estadoPedido"
        ] == "ANULADO"
        and mongo_final[
            "stockDisponible"
        ] == 20
        and mongo_final[
            "stockReservado"
        ] == 0
        and mongo_final[
            "stockTotal"
        ] == 20
    ):
        raise RuntimeError(
            "Pedido/stock final inconsistente"
        )

    compensaciones = (
        mongo_final.get(
            "compensaciones"
        ) or []
    )

    pasos_comp = [
        c.get("Paso")
        for c in compensaciones
    ]

    estados_comp = [
        c.get("Estado")
        for c in compensaciones
    ]

    print(
        "   Compensaciones="
        + " -> ".join(pasos_comp)
    )

    if pasos_comp != [
        "ANULAR_GUIA",
        "LIBERAR_STOCK"
    ]:
        raise RuntimeError(
            "Orden de compensación "
            f"incorrecto: {pasos_comp}"
        )

    if estados_comp != [
        "OK",
        "OK"
    ]:
        raise RuntimeError(
            "Alguna compensación "
            f"no terminó OK: {estados_comp}"
        )

    print(
        "10. Validando que no exista "
        "guía ACTIVA en el transportista..."
    )

    status_t, trans = http(
        f"{TRANSPORTISTA}/guias?"
        f"pedidoId="
        f"{urllib.parse.quote(pedido_id)}"
    )

    guias = []

    if (
        status_t == 200
        and isinstance(trans, dict)
    ):
        guias = (
            trans.get("guias") or []
        )

    activas = [
        g
        for g in guias
        if g.get("estado") == "ACTIVA"
    ]

    resultado["transportistaFinal"] = {
        "http": status_t,
        "cantidadDevuelta": len(guias),
        "activas": len(activas),
        "respuesta": trans
    }

    print(
        f"   HTTP={status_t}, "
        f"guías devueltas={len(guias)}, "
        f"activas={len(activas)}"
    )

    # El simulador consulta solo guías activas.
    # Después de anular es correcto recibir
    # 404 o 200 con arreglo vacío.
    if not (
        status_t in (200, 404)
        and len(activas) == 0
    ):
        raise RuntimeError(
            "Quedó una guía activa "
            "después de la compensación"
        )

    resultado["validaciones"] = {
        "anulacionAlcanzoProceso":
            True,
        "pedidoAnulado":
            True,
        "stockLiberado":
            True,
        "sinGuiaActiva":
            True,
        "ordenCompensacionCorrecto":
            True,
        "compensacionesOK":
            True
    }

    resultado["resultado"] = "PASS"

    print()
    print("✅ E2E 09: PASS")

except Exception as e:
    resultado["error"] = str(e)

    print()
    print(
        f"❌ E2E 09: FAIL - {e}"
    )


with open(
    EVIDENCIA,
    "w",
    encoding="utf-8"
) as f:
    json.dump(
        resultado,
        f,
        ensure_ascii=False,
        indent=2,
        default=str
    )

print(
    f"Evidencia JSON: {EVIDENCIA}"
)

raise SystemExit(
    0
    if resultado["resultado"] == "PASS"
    else 1
)
