import json
import os
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = "http://localhost:8080/api/java"
TRANSPORTISTA = "http://localhost:9090"
PROXY = "http://localhost:19090"

MONGO_URI = (
    "mongodb://localhost:27017/"
    "pedidos_stock?directConnection=true"
)

COMPOSE = [
    "docker", "compose",
    "-f", "docker-compose.yml",
    "-f", "tests/integration/e2e12-compose.override.yml"
]

EVIDENCIA = "tests/evidencias/e2e12-reinicio-despachos.json"

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
        COMPOSE + [
            "exec", "-T",
            "mongodb",
            "mongosh", "--quiet",
            MONGO_URI,
            "--eval", js
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

            if not raw:
                return r.status, {}

            return r.status, json.loads(raw)

    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8")

        try:
            payload = json.loads(raw)
        except Exception:
            payload = {"raw": raw}

        return e.code, payload

    except urllib.error.URLError as e:
        return 0, {
            "error": str(e)
        }


resultado = {
    "escenario":
        "E2E 12 - Reinicio despachos con pedido en curso",
    "resultado": "FAIL"
}


try:
    print("1. Restableciendo entorno limpio...")

    cmd(
        COMPOSE + [
            "down",
            "-v",
            "--remove-orphans"
        ]
    )

    env = os.environ.copy()
    env["FAILURE_RATE"] = "0"
    env["PARTIAL_RATE"] = "0"

    cmd(
        COMPOSE + [
            "up",
            "-d",
            "--no-build",
            "--wait",
            "--wait-timeout", "240"
        ],
        env=env
    )

    print("   Docker Compose + proxy: OK")

    print("2. Validando proxy E2E12...")

    status_proxy, proxy_health = http(
        f"{PROXY}/test-health"
    )

    if status_proxy != 200:
        raise RuntimeError(
            "Proxy E2E12 no está disponible"
        )

    print("   Proxy: UP")

    print("3. Login comprador01...")

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

    print("4. Validando stock inicial...")

    stock_inicial = mongo("""
const s = db.Stock.findOne({
  IdProducto:"SKU-00002",
  IdAlmacen:"ALM-01"
});

print(JSON.stringify({
  disponible:s.CantidadStock,
  reservado:s.ReservaStock
}));
""")

    print(json.dumps(
        stock_inicial,
        indent=2,
        ensure_ascii=False
    ))

    if not (
        stock_inicial["disponible"] == 20
        and stock_inicial["reservado"] == 0
    ):
        raise RuntimeError(
            "Stock inicial esperado 20 / 0"
        )

    resultado["stockInicial"] = stock_inicial

    print("5. Creando pedido...")

    status_alta, alta = http(
        f"{BASE}/pedidos",
        "POST",
        {
            "solicitudId":
                "E2E12-REINICIO-DESPACHOS-001",
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

    pedido_id = (
        (alta.get("data") or {})
        .get("pedidoId")
    )

    print(
        f"   HTTP={status_alta}, "
        f"pedidoId={pedido_id}"
    )

    if status_alta != 202 or not pedido_id:
        raise RuntimeError(
            "No se pudo crear el pedido"
        )

    resultado["pedidoId"] = pedido_id

    print(
        "6. Esperando que el transportista REAL "
        "cree la guía y el proxy retenga la respuesta..."
    )

    proxy_status = None

    for intento in range(1, 201):
        status, data = http(
            f"{PROXY}/test-status",
            timeout=2
        )

        if (
            status == 200
            and data.get("guiaCreada") is True
            and data.get("pedidoId") == pedido_id
        ):
            proxy_status = data

            print(
                "   Guía creada externamente. "
                f"Polling={intento}"
            )
            break

        time.sleep(0.05)

    resultado["proxyAntesCaida"] = proxy_status

    if proxy_status is None:
        raise RuntimeError(
            "El proxy no detectó la creación "
            "de guía"
        )

    print(json.dumps(
        proxy_status,
        indent=2,
        ensure_ascii=False
    ))

    print(
        "7. Verificando pedido justo antes "
        "del SIGKILL..."
    )

    punto = mongo(f"""
const p = db.Pedido.findOne({{
  _id:"{pedido_id}"
}});

const w = db.Worker.findOne({{
  _id:p.IdWorker
}});

const s = db.Stock.findOne({{
  IdProducto:"SKU-00002",
  IdAlmacen:"ALM-01"
}});

print(JSON.stringify({{
  estado:p.IdEstado,
  idWorker:p.IdWorker,
  fechaInicioProceso:p.FechaInicioProceso,
  fechaFinProceso:p.FechaFinProceso,
  intentoProceso:p.IntentoProceso,
  estadoReserva:p.EstadoReserva,
  guiaIntentada:p.GuiaIntentada,
  envio:p.Envio,

  workerFechaFin:w.FechaFin,
  workerIntentos:w.Intentos,
  workerLeaseOwner:w.LeaseOwner,
  workerLeaseVersion:Number(w.LeaseVersion),
  workerLeaseHeartbeat:w.LeaseHeartbeat,

  stockDisponible:s.CantidadStock,
  stockReservado:s.ReservaStock,

  guiasMongo:
    db.Guia.countDocuments({{
      IdPedido:p._id
    }})
}}));
""")

    resultado["puntoCorte"] = punto

    print(json.dumps(
        punto,
        indent=2,
        ensure_ascii=False
    ))

    if not (
        punto["estado"] == "EN_PROCESO"
        and punto["fechaFinProceso"] is None
        and punto["intentoProceso"] == 1
        and punto["estadoReserva"]
            == "RESERVADA"
        and punto["guiaIntentada"] is True
        and punto["workerFechaFin"] is None
        and punto["stockDisponible"] == 19
        and punto["stockReservado"] == 1
    ):
        raise RuntimeError(
            "El pedido no está en el punto "
            "esperado antes del reinicio"
        )

    worker_id = punto["idWorker"]

    print()
    print(
        "8. SIGKILL despachos-dotnet "
        "durante GENERAR_GUIA..."
    )

    cmd(
        COMPOSE + [
            "kill",
            "-s", "SIGKILL",
            "despachos-dotnet"
        ]
    )

    print("   despachos-dotnet detenido.")

    resultado["comandoCaida"] = (
        "docker compose "
        "-f docker-compose.yml "
        "-f tests/integration/"
        "e2e12-compose.override.yml "
        "kill -s SIGKILL despachos-dotnet"
    )

    print(
        "9. Confirmando guía externa "
        "existente después de la caída..."
    )

    status_t1, trans1 = http(
        f"{TRANSPORTISTA}/guias?"
        f"pedidoId="
        f"{urllib.parse.quote(pedido_id)}"
    )

    guias_ext_antes = (
        trans1.get("guias", [])
        if status_t1 == 200
        else []
    )

    print(
        f"   HTTP={status_t1}, "
        f"guías={len(guias_ext_antes)}"
    )

    resultado["transportistaTrasCaida"] = {
        "http": status_t1,
        "cantidad": len(guias_ext_antes),
        "respuesta": trans1
    }

    if not (
        status_t1 == 200
        and len(guias_ext_antes) == 1
    ):
        raise RuntimeError(
            "Se esperaba exactamente una "
            "guía externa tras la caída"
        )

    print(
        "10. Confirmando pedido/Worker "
        "incompletos..."
    )

    interrumpido = mongo(f"""
const p = db.Pedido.findOne({{
  _id:"{pedido_id}"
}});

const w = db.Worker.findOne({{
  _id:"{worker_id}"
}});

print(JSON.stringify({{
  estado:p.IdEstado,
  fechaFinProceso:p.FechaFinProceso,
  intentoProceso:p.IntentoProceso,
  estadoReserva:p.EstadoReserva,
  guiaIntentada:p.GuiaIntentada,

  workerFechaFin:w.FechaFin,
  workerIntentos:w.Intentos,
  workerLeaseVersion:Number(w.LeaseVersion),
  workerLeaseHeartbeat:w.LeaseHeartbeat,

  guiasMongo:
    db.Guia.countDocuments({{
      IdPedido:p._id
    }})
}}));
""")

    resultado["interrumpido"] = interrumpido

    print(json.dumps(
        interrumpido,
        indent=2,
        ensure_ascii=False
    ))

    if not (
        interrumpido["estado"] == "EN_PROCESO"
        and interrumpido["fechaFinProceso"] is None
        and interrumpido["workerFechaFin"] is None
    ):
        raise RuntimeError(
            "El pedido no quedó incompleto "
            "tras la caída"
        )

    print()
    print("11. Reiniciando despachos-dotnet...")

    cmd(
        COMPOSE + [
            "up",
            "-d",
            "despachos-dotnet"
        ],
        env=env
    )

    print(
        "   Servicio levantado. "
        "Esperando expiración natural "
        "del lease (~30 s)..."
    )

    resultado["comandoReinicio"] = (
        "docker compose "
        "-f docker-compose.yml "
        "-f tests/integration/"
        "e2e12-compose.override.yml "
        "up -d despachos-dotnet"
    )

    inicio = time.time()
    final = None

    print(
        "12. Esperando recuperación "
        "y estado terminal..."
    )

    for intento in range(1, 181):
        dato = mongo(f"""
const p = db.Pedido.findOne({{
  _id:"{pedido_id}"
}});

const w = db.Worker.findOne({{
  _id:"{worker_id}"
}});

print(JSON.stringify({{
  estado:p?.IdEstado ?? null,
  fechaFinProceso:
    p?.FechaFinProceso ?? null,
  intentoProceso:
    p?.IntentoProceso ?? null,
  estadoReserva:
    p?.EstadoReserva ?? null,

  workerFechaFin:
    w?.FechaFin ?? null,
  workerIntentos:
    w?.Intentos ?? null,
  workerLeaseVersion:
    Number(w?.LeaseVersion ?? 0)
}}));
""")

        if (
            dato["estado"] in {
                "DESPACHADO",
                "ANULADO",
                "REQUIERE_REVISION"
            }
            and dato["fechaFinProceso"]
                is not None
            and dato["workerFechaFin"]
                is not None
        ):
            final = dato
            final["polling"] = intento
            final["segundosRecuperacion"] = round(
                time.time() - inicio,
                2
            )

            print(
                f"   Estado={dato['estado']}, "
                f"IntentoProceso="
                f"{dato['intentoProceso']}, "
                f"Worker.Intentos="
                f"{dato['workerIntentos']}, "
                f"tiempo="
                f"{final['segundosRecuperacion']}s"
            )
            break

        time.sleep(0.5)

    resultado["recuperacion"] = final

    if final is None:
        raise RuntimeError(
            "Pedido no alcanzó estado terminal "
            "después del reinicio"
        )

    if final["workerIntentos"] < 2:
        raise RuntimeError(
            "Worker.Intentos no aumentó"
        )

    if (
        final["workerLeaseVersion"]
        <= punto["workerLeaseVersion"]
    ):
        raise RuntimeError(
            "LeaseVersion no aumentó"
        )

    if final["intentoProceso"] < 2:
        raise RuntimeError(
            "IntentoProceso no aumentó"
        )

    print()
    print(
        "13. Validando estado final, "
        "stock, guía y procesos..."
    )

    detalle = mongo(f"""
const p = db.Pedido.findOne({{
  _id:"{pedido_id}"
}});

const w = db.Worker.findOne({{
  _id:"{worker_id}"
}});

const s = db.Stock.findOne({{
  IdProducto:"SKU-00002",
  IdAlmacen:"ALM-01"
}});

const guias = db.Guia.find({{
  IdPedido:"{pedido_id}"
}}).toArray();

const procesos = db.PedidoProceso
  .find({{IdPedido:"{pedido_id}"}})
  .sort({{FechaCreacion:1}})
  .toArray();

print(JSON.stringify({{
  estado:p.IdEstado,
  fechaFinProceso:p.FechaFinProceso,
  intentoProceso:p.IntentoProceso,
  estadoReserva:p.EstadoReserva,

  workerFechaFin:w.FechaFin,
  workerIntentos:w.Intentos,
  workerLeaseVersion:Number(w.LeaseVersion),

  stockDisponible:s.CantidadStock,
  stockReservado:s.ReservaStock,

  guiasMongo:guias.length,
  guias:guias.map(g => ({{
    id:g._id,
    numero:g.Numero,
    estado:g.IdEstado
  }})),

  procesos:procesos.map(x => ({{
    id:x._id,
    paso:x.Paso,
    estado:x.IdEstadoProceso,
    nroIntento:x.NroIntento
  }}))
}}));
""")

    resultado["finalMongo"] = detalle

    print(json.dumps(
        detalle,
        indent=2,
        ensure_ascii=False
    ))

    if detalle["estado"] == "DESPACHADO":
        if not (
            detalle["stockDisponible"] == 19
            and detalle["stockReservado"] == 0
            and detalle["estadoReserva"]
                == "CONFIRMADA"
            and detalle["guiasMongo"] == 1
        ):
            raise RuntimeError(
                "Estado DESPACHADO "
                "pero datos inconsistentes"
            )

    elif detalle["estado"] == "ANULADO":
        if not (
            detalle["stockDisponible"] == 20
            and detalle["stockReservado"] == 0
        ):
            raise RuntimeError(
                "Estado ANULADO "
                "pero stock inconsistente"
            )

    elif detalle["estado"] != "REQUIERE_REVISION":
        raise RuntimeError(
            f"Estado terminal inesperado: "
            f"{detalle['estado']}"
        )

    if (
        detalle["stockDisponible"] < 0
        or detalle["stockReservado"] < 0
    ):
        raise RuntimeError(
            "Stock negativo"
        )

    print()
    print(
        "14. Validando que NO exista "
        "segunda guía externa..."
    )

    status_t2, trans2 = http(
        f"{TRANSPORTISTA}/guias?"
        f"pedidoId="
        f"{urllib.parse.quote(pedido_id)}"
    )

    guias_ext = (
        trans2.get("guias", [])
        if status_t2 == 200
        else []
    )

    activas = [
        g for g in guias_ext
        if g.get("estado") == "ACTIVA"
    ]

    print(
        f"   HTTP={status_t2}, "
        f"guías={len(guias_ext)}, "
        f"activas={len(activas)}"
    )

    resultado["transportistaFinal"] = {
        "http": status_t2,
        "cantidad": len(guias_ext),
        "activas": len(activas),
        "respuesta": trans2
    }

    if len(guias_ext) > 1:
        raise RuntimeError(
            "Se generó más de una guía "
            "externa"
        )

    if detalle["estado"] == "DESPACHADO":
        if not (
            status_t2 == 200
            and len(guias_ext) == 1
            and len(activas) == 1
        ):
            raise RuntimeError(
                "Guía externa inconsistente "
                "para DESPACHADO"
            )

    resultado["validaciones"] = {
        "guiaCreadaAntesDeCaida": True,
        "caidaDurantePedido": True,
        "workerQuedoAbierto": True,
        "pedidoQuedoIncompleto": True,
        "servicioReiniciado": True,
        "leaseRecuperado": True,
        "workerIntentosIncrementado": True,
        "leaseVersionIncrementado": True,
        "intentoProcesoIncrementado": True,
        "estadoTerminal": True,
        "stockConsistente": True,
        "sinGuiaDuplicada": True
    }

    resultado["resultado"] = "PASS"

    print()
    print("✅ E2E 12: PASS")

except Exception as e:
    resultado["error"] = str(e)

    print()
    print(
        f"❌ E2E 12: FAIL - {e}"
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
