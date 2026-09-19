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

EVIDENCIA = "tests/evidencias/e2e11-tarea-repetida.json"

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


def esperar_final(pedido_id, token):
    for intento in range(1, 121):
        status, response = http(
            f"{BASE}/pedidos/{pedido_id}",
            token=token
        )

        data = response.get("data") or {}
        estado = data.get("estado")

        if estado in {
            "DESPACHADO",
            "ANULADO",
            "REQUIERE_REVISION"
        }:
            return estado, intento

        time.sleep(0.5)

    raise RuntimeError("Timeout esperando estado final")


resultado = {
    "escenario": "E2E 11 - Tarea repetida",
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

    cmd([
        "docker", "compose",
        "up", "-d",
        "--no-build",
        "--wait",
        "--wait-timeout", "240"
    ], env=env)

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

    print("3. Creando pedido normal...")

    status_alta, alta = http(
        f"{BASE}/pedidos",
        "POST",
        {
            "solicitudId": "E2E11-TAREA-REPETIDA-001",
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
    )

    print(
        f"   HTTP={status_alta}, "
        f"pedidoId={pedido_id}"
    )

    if status_alta != 202 or not pedido_id:
        raise RuntimeError(
            "No se pudo crear el pedido"
        )

    print("4. Esperando DESPACHADO...")

    estado, polling = esperar_final(
        pedido_id,
        token
    )

    print(
        f"   Estado={estado}, "
        f"polling={polling}"
    )

    if estado != "DESPACHADO":
        raise RuntimeError(
            f"Se esperaba DESPACHADO, "
            f"se obtuvo {estado}"
        )

    print("5. Capturando baseline...")

    antes = mongo(f"""
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

const procesos = db.PedidoProceso
    .find({{IdPedido:p._id}})
    .sort({{FechaCreacion:1}})
    .toArray();

const guias = db.Guia
    .find({{IdPedido:p._id}})
    .toArray();

print(JSON.stringify({{
    pedidoId:p._id,
    estado:p.IdEstado,
    idWorker:p.IdWorker,
    fechaFinProceso:p.FechaFinProceso,
    intentoProceso:p.IntentoProceso,
    estadoReserva:p.EstadoReserva,

    workerFechaFin:w.FechaFin,
    workerIntentos:w.Intentos,
    workerLeaseOwner:w.LeaseOwner,
    workerLeaseVersion:Number(w.LeaseVersion),
    workerLeaseHeartbeat:w.LeaseHeartbeat,

    stockDisponible:s.CantidadStock,
    stockReservado:s.ReservaStock,

    guiasMongo:guias.length,
    guiaIds:guias.map(x => x._id),

    procesosTotal:procesos.length,
    procesos:procesos.map(x => ({{
        id:x._id,
        paso:x.Paso,
        estado:x.IdEstadoProceso,
        nroIntento:x.NroIntento
    }}))
}}));
""")

    resultado["antes"] = antes

    print(json.dumps(
        antes,
        indent=2,
        ensure_ascii=False
    ))

    if not (
        antes["estado"] == "DESPACHADO"
        and antes["fechaFinProceso"] is not None
        and antes["workerFechaFin"] is not None
        and antes["workerIntentos"] == 1
        and antes["stockDisponible"] == 19
        and antes["stockReservado"] == 0
        and antes["guiasMongo"] == 1
    ):
        raise RuntimeError(
            "Baseline previo inválido"
        )

    worker_id = antes["idWorker"]

    print()
    print("6. Venciendo MANUALMENTE la tarea ya procesada...")

    js_mutacion = f'''const workerId="{worker_id}";
db.Worker.updateOne(
  {{
    _id:workerId,
    FechaFin:{{$ne:null}}
  }},
  {{
    $set:{{
      FechaFin:null,
      LeaseOwner:"e2e11-owner-vencido",
      LeaseHeartbeat:new Date(Date.now()-120000),
      FechaModificacion:new Date(),
      UsuarioModificacion:"e2e11"
    }}
  }}
);'''

    comando_exacto = (
        'docker compose exec -T mongodb '
        'mongosh --quiet '
        '"mongodb://localhost:27017/'
        'pedidos_stock?directConnection=true" '
        f"--eval '{js_mutacion}'"
    )

    resultado["comandoMongoExacto"] = comando_exacto
    resultado["javascriptMongo"] = js_mutacion

    print("=== COMANDO MONGO EXACTO ===")
    print(comando_exacto)
    print("============================")

    mutacion = mongo(
        js_mutacion
        + f'''
const w = db.Worker.findOne({{
    _id:"{worker_id}"
}});

print(JSON.stringify({{
    fechaFin:w.FechaFin,
    intentos:w.Intentos,
    leaseOwner:w.LeaseOwner,
    leaseVersion:Number(w.LeaseVersion),
    leaseHeartbeat:w.LeaseHeartbeat
}}));
'''
    )

    resultado["despuesMutacion"] = mutacion

    print(json.dumps(
        mutacion,
        indent=2,
        ensure_ascii=False
    ))

    print()
    print("7. Esperando que el Worker vuelva a tomar la tarea...")

    recuperado = None

    for intento in range(1, 121):
        actual = mongo(f"""
const w = db.Worker.findOne({{
    _id:"{worker_id}"
}});

print(JSON.stringify({{
    fechaFin:w?.FechaFin ?? null,
    intentos:w?.Intentos ?? null,
    leaseOwner:w?.LeaseOwner ?? null,
    leaseVersion:Number(
        w?.LeaseVersion ?? 0
    ),
    leaseHeartbeat:
        w?.LeaseHeartbeat ?? null
}}));
""")

        if (
            actual["fechaFin"] is not None
            and actual["intentos"] >= 2
            and actual["leaseVersion"]
                > antes["workerLeaseVersion"]
        ):
            recuperado = actual
            print(
                "   Worker retomado y cerrado "
                f"en polling={intento}"
            )
            break

        time.sleep(0.5)

    resultado["recuperacion"] = recuperado

    if recuperado is None:
        raise RuntimeError(
            "La tarea vencida no fue retomada"
        )

    print(json.dumps(
        recuperado,
        indent=2,
        ensure_ascii=False
    ))

    print()
    print("8. Verificando que NO se repitieron efectos...")

    despues = mongo(f"""
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

const procesos = db.PedidoProceso
    .find({{IdPedido:p._id}})
    .sort({{FechaCreacion:1}})
    .toArray();

const guias = db.Guia
    .find({{IdPedido:p._id}})
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
    guiaIds:guias.map(x => x._id),

    procesosTotal:procesos.length,
    procesos:procesos.map(x => ({{
        id:x._id,
        paso:x.Paso,
        estado:x.IdEstadoProceso,
        nroIntento:x.NroIntento
    }}))
}}));
""")

    resultado["despues"] = despues

    print(json.dumps(
        despues,
        indent=2,
        ensure_ascii=False
    ))

    if despues["estado"] != antes["estado"]:
        raise RuntimeError(
            "Cambió el estado del pedido"
        )

    if (
        despues["fechaFinProceso"]
        != antes["fechaFinProceso"]
    ):
        raise RuntimeError(
            "Cambió FechaFinProceso del pedido"
        )

    if (
        despues["intentoProceso"]
        != antes["intentoProceso"]
    ):
        raise RuntimeError(
            "El pedido fue tomado nuevamente; "
            "debía mantenerse ya procesado"
        )

    if (
        despues["stockDisponible"]
        != antes["stockDisponible"]
        or despues["stockReservado"]
        != antes["stockReservado"]
    ):
        raise RuntimeError(
            "La tarea repetida cambió el stock"
        )

    if (
        despues["guiasMongo"]
        != antes["guiasMongo"]
        or despues["guiaIds"]
        != antes["guiaIds"]
    ):
        raise RuntimeError(
            "La tarea repetida cambió las guías Mongo"
        )

    if (
        despues["procesosTotal"]
        != antes["procesosTotal"]
        or despues["procesos"]
        != antes["procesos"]
    ):
        raise RuntimeError(
            "La tarea repetida agregó o modificó pasos"
        )

    if (
        despues["workerIntentos"]
        <= antes["workerIntentos"]
    ):
        raise RuntimeError(
            "No se demuestra la reentrega del Worker"
        )

    if (
        despues["workerLeaseVersion"]
        <= antes["workerLeaseVersion"]
    ):
        raise RuntimeError(
            "LeaseVersion no aumentó"
        )

    print()
    print("9. Validando transportista externo...")

    status_t, trans = http(
        f"{TRANSPORTISTA}/guias?"
        f"pedidoId={urllib.parse.quote(pedido_id)}"
    )

    guias_ext = (
        trans.get("guias", [])
        if status_t == 200
        else []
    )

    activas = [
        g for g in guias_ext
        if g.get("estado") == "ACTIVA"
    ]

    resultado["transportista"] = {
        "http": status_t,
        "cantidad": len(guias_ext),
        "activas": len(activas),
        "respuesta": trans
    }

    print(
        f"   HTTP={status_t}, "
        f"guías={len(guias_ext)}, "
        f"activas={len(activas)}"
    )

    if not (
        status_t == 200
        and len(guias_ext) == 1
        and len(activas) == 1
    ):
        raise RuntimeError(
            "La tarea repetida alteró "
            "las guías del transportista"
        )

    resultado["validaciones"] = {
        "workerVencidoManualmente": True,
        "workerRetomado": True,
        "workerIntentosIncrementado": True,
        "leaseVersionIncrementado": True,
        "estadoPedidoNoCambio": True,
        "intentoPedidoNoCambio": True,
        "stockNoCambio": True,
        "guiaMongoNoCambio": True,
        "guiaTransportistaNoCambio": True,
        "pasosNoDuplicados": True
    }

    resultado["resultado"] = "PASS"

    print()
    print("✅ E2E 11: PASS")

except Exception as e:
    resultado["error"] = str(e)

    print()
    print(f"❌ E2E 11: FAIL - {e}")


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

print(f"Evidencia JSON: {EVIDENCIA}")

raise SystemExit(
    0
    if resultado["resultado"] == "PASS"
    else 1
)
