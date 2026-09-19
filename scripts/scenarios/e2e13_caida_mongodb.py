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
MONGO_URI = "mongodb://localhost:27017/pedidos_stock?directConnection=true"

COMPOSE = [
    "docker", "compose",
    "-f", "docker-compose.yml",
    "-f", "tests/integration/e2e13-compose.override.yml"
]

EVIDENCIA = "tests/evidencias/e2e13-caida-mongodb.json"
os.makedirs("tests/evidencias", exist_ok=True)


def cmd(args, env=None, check=True):
    p = subprocess.run(args, text=True, capture_output=True, env=env)
    if check and p.returncode != 0:
        raise RuntimeError(
            f"Comando falló: {' '.join(args)}\n"
            f"{p.stdout}\n{p.stderr}"
        )
    return p.stdout.strip()


def http(url, method="GET", body=None, token=None, timeout=20):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    data = None if body is None else json.dumps(body).encode()

    req = urllib.request.Request(
        url, data=data, headers=headers, method=method
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode()
            return r.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, {"raw": raw}
    except Exception as e:
        return 0, {"error": str(e)}


def mongo(js):
    out = cmd(COMPOSE + [
        "exec", "-T", "mongodb",
        "mongosh", "--quiet", MONGO_URI,
        "--eval", js
    ])

    lines = [x.strip() for x in out.splitlines() if x.strip()]
    return json.loads(lines[-1])


resultado = {
    "escenario": "E2E 13 - Caida MongoDB durante pedido",
    "resultado": "FAIL"
}


try:
    print("1. Restableciendo entorno limpio...")

    cmd(COMPOSE + ["down", "-v", "--remove-orphans"])

    env = os.environ.copy()
    env["FAILURE_RATE"] = "0"
    env["PARTIAL_RATE"] = "0"

    cmd(COMPOSE + [
        "up", "-d", "--no-build",
        "--wait", "--wait-timeout", "240"
    ], env=env)

    print("   Docker Compose + proxy: OK")

    print("2. Login comprador01...")

    st, login = http(
        f"{BASE}/auth/login",
        "POST",
        {"usuario": "comprador01", "clave": "Reto2026!"}
    )

    if st != 200:
        raise RuntimeError("Login falló")

    token = login["data"]["accessToken"]

    print("3. Creando pedido...")

    st, alta = http(
        f"{BASE}/pedidos",
        "POST",
        {
            "solicitudId": "E2E13-CAIDA-MONGO-001",
            "almacenId": "ALM-01",
            "zonaEntrega": "LIMA_METROPOLITANA",
            "items": [{"sku": "SKU-00002", "cantidad": 1}]
        },
        token
    )

    pedido_id = (alta.get("data") or {}).get("pedidoId")

    print(f"   HTTP={st}, pedidoId={pedido_id}")

    if st != 202 or not pedido_id:
        raise RuntimeError("No se creó pedido")

    resultado["pedidoId"] = pedido_id

    print("4. Esperando guía externa con respuesta retenida...")

    detectado = None

    for i in range(200):
        stp, d = http(f"{PROXY}/test-status", timeout=2)

        if (
            stp == 200
            and d.get("guiaCreada") is True
            and d.get("pedidoId") == pedido_id
        ):
            detectado = d
            print(f"   Guía externa creada. polling={i+1}")
            break

        time.sleep(0.05)

    if detectado is None:
        raise RuntimeError("Proxy no detectó guía")

    punto = mongo(f'''
const p=db.Pedido.findOne({{_id:"{pedido_id}"}});
const s=db.Stock.findOne({{
  IdProducto:"SKU-00002",
  IdAlmacen:"ALM-01"
}});
print(JSON.stringify({{
  estado:p.IdEstado,
  idWorker:p.IdWorker,
  fechaFinProceso:p.FechaFinProceso,
  intentoProceso:p.IntentoProceso,
  estadoReserva:p.EstadoReserva,
  guiaIntentada:p.GuiaIntentada,
  stockDisponible:s.CantidadStock,
  stockReservado:s.ReservaStock,
  guiasMongo:db.Guia.countDocuments({{IdPedido:p._id}})
}}));
''')

    print(json.dumps(punto, indent=2, ensure_ascii=False))
    resultado["puntoCaida"] = punto

    if not (
        punto["estado"] == "EN_PROCESO"
        and punto["fechaFinProceso"] is None
        and punto["estadoReserva"] == "RESERVADA"
        and punto["guiaIntentada"] is True
        and punto["stockDisponible"] == 19
        and punto["stockReservado"] == 1
    ):
        raise RuntimeError("Punto de caída inválido")

    print("5. Deteniendo MongoDB...")

    cmd(COMPOSE + ["stop", "mongodb"])
    resultado["comandoCaida"] = "docker compose ... stop mongodb"

    print("   MongoDB detenido.")

    print("6. Confirmando que MongoDB está realmente detenido...")

    ps = cmd([
        "docker", "inspect",
        "-f", "{{.State.Running}}",
        cmd(COMPOSE + ["ps", "-a", "-q", "mongodb"])
    ])

    if ps.strip().lower() != "false":
        raise RuntimeError("MongoDB continúa ejecutándose")

    print("   MongoDB: DOWN")

    print("7. Manteniendo la caída durante el procesamiento...")
    time.sleep(12)

    print("8. Levantando MongoDB nuevamente...")

    cmd(COMPOSE + ["up", "-d", "--wait", "mongodb"], env=env)

    print("   MongoDB: UP")
    resultado["comandoRecuperacion"] = "docker compose ... up -d --wait mongodb"

    print("9. Esperando estado final del pedido...")

    inicio = time.time()
    final_api = None

    for i in range(240):
        st, r = http(
            f"{BASE}/pedidos/{pedido_id}",
            token=token,
            timeout=3
        )

        if st == 200:
            estado = (r.get("data") or {}).get("estado")

            if estado in {
                "DESPACHADO",
                "ANULADO",
                "REQUIERE_REVISION"
            }:
                final_api = {
                    "estado": estado,
                    "polling": i + 1,
                    "segundos": round(time.time() - inicio, 2)
                }
                print(
                    f"   Estado={estado}, "
                    f"tiempo={final_api['segundos']}s"
                )
                break

        time.sleep(0.5)

    if final_api is None:
        raise RuntimeError(
            "Pedido no alcanzó estado terminal tras recuperar MongoDB"
        )

    resultado["finalApi"] = final_api

    print("10. Validando estado final en MongoDB...")

    final = mongo(f'''
const p=db.Pedido.findOne({{_id:"{pedido_id}"}});
const w=db.Worker.findOne({{_id:p.IdWorker}});
const s=db.Stock.findOne({{
  IdProducto:"SKU-00002",
  IdAlmacen:"ALM-01"
}});
const g=db.Guia.find({{IdPedido:p._id}}).toArray();

print(JSON.stringify({{
  estado:p.IdEstado,
  fechaFinProceso:p.FechaFinProceso,
  intentoProceso:p.IntentoProceso,
  estadoReserva:p.EstadoReserva,
  workerFechaFin:w?.FechaFin ?? null,
  workerIntentos:w?.Intentos ?? null,
  workerLeaseVersion:Number(w?.LeaseVersion ?? 0),
  stockDisponible:s.CantidadStock,
  stockReservado:s.ReservaStock,
  totalStock:s.CantidadStock+s.ReservaStock,
  guiasMongo:g.length,
  guias:g.map(x=>({{
    numero:x.Numero,
    estado:x.IdEstado
  }}))
}}));
''')

    print(json.dumps(final, indent=2, ensure_ascii=False))
    resultado["finalMongo"] = final

    if final["estado"] not in {
        "DESPACHADO",
        "ANULADO",
        "REQUIERE_REVISION"
    }:
        raise RuntimeError("Estado final inválido")

    if final["fechaFinProceso"] is None:
        raise RuntimeError("Pedido quedó incompleto")

    if final["stockDisponible"] < 0 or final["stockReservado"] < 0:
        raise RuntimeError("Stock negativo")

    if final["estado"] == "DESPACHADO":
        if not (
            final["stockDisponible"] == 19
            and final["stockReservado"] == 0
            and final["guiasMongo"] == 1
        ):
            raise RuntimeError("Despacho inconsistente")

    elif final["estado"] == "ANULADO":
        if not (
            final["stockDisponible"] == 20
            and final["stockReservado"] == 0
        ):
            raise RuntimeError("Anulación inconsistente")

    else:
        if final["totalStock"] != 20:
            raise RuntimeError("Stock inconsistente en revisión")

    print("11. Validando transportista...")

    stt, rt = http(
        f"{TRANSPORTISTA}/guias?"
        f"pedidoId={urllib.parse.quote(pedido_id)}"
    )

    guias = rt.get("guias", []) if stt == 200 else []
    activas = [x for x in guias if x.get("estado") == "ACTIVA"]

    print(
        f"   HTTP={stt}, guías={len(guias)}, activas={len(activas)}"
    )

    if len(guias) > 1 or len(activas) > 1:
        raise RuntimeError("Guía duplicada")

    resultado["transportista"] = {
        "http": stt,
        "guias": len(guias),
        "activas": len(activas)
    }

    resultado["resultado"] = "PASS"

    print()
    print("✅ E2E 13: PASS")

except Exception as e:
    resultado["error"] = str(e)
    print()
    print(f"❌ E2E 13: FAIL - {e}")


with open(EVIDENCIA, "w", encoding="utf-8") as f:
    json.dump(
        resultado,
        f,
        indent=2,
        ensure_ascii=False,
        default=str
    )

print(f"Evidencia JSON: {EVIDENCIA}")

raise SystemExit(0 if resultado["resultado"] == "PASS" else 1)
