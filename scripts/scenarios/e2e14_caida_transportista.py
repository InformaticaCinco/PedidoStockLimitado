import json
import os
import subprocess
import time
import urllib.error
import urllib.request

BASE = "http://localhost:8080/api/java"
MONGO = "mongodb://localhost:27017/pedidos_stock?directConnection=true"
EVIDENCIA = "tests/evidencias/e2e14-caida-transportista.json"

os.makedirs("tests/evidencias", exist_ok=True)

def cmd(args, env=None):
    p = subprocess.run(args, text=True, capture_output=True, env=env)
    if p.returncode != 0:
        raise RuntimeError(f"{' '.join(args)}\n{p.stdout}\n{p.stderr}")
    return p.stdout.strip()

def http(url, method="GET", body=None, token=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    req = urllib.request.Request(
        url,
        data=None if body is None else json.dumps(body).encode(),
        headers=headers,
        method=method
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            raw = r.read().decode()
            return r.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        return e.code, json.loads(raw) if raw else {}

def mongo(js):
    out = cmd([
        "docker","compose","exec","-T","mongodb",
        "mongosh","--quiet",MONGO,"--eval",js
    ])
    return json.loads([x for x in out.splitlines() if x.strip()][-1])

r = {"escenario":"E2E 14 - Caida transportista","resultado":"FAIL"}

try:
    print("1. Restableciendo entorno...")
    cmd(["docker","compose","down","-v","--remove-orphans"])

    env = os.environ.copy()
    env["FAILURE_RATE"] = "0"
    env["PARTIAL_RATE"] = "0"

    cmd([
        "docker","compose","up","-d","--no-build",
        "--wait","--wait-timeout","240"
    ], env=env)
    print("   Docker Compose: OK")

    print("2. Login...")
    st, login = http(
        f"{BASE}/auth/login","POST",
        {"usuario":"comprador01","clave":"Reto2026!"}
    )
    assert st == 200
    token = login["data"]["accessToken"]

    print("3. Stock inicial...")
    inicial = mongo('''
const s=db.Stock.findOne({IdProducto:"SKU-00002",IdAlmacen:"ALM-01"});
print(JSON.stringify({
 disponible:s.CantidadStock,
 reservado:s.ReservaStock,
 total:s.CantidadStock+s.ReservaStock
}));
''')
    print(inicial)
    assert inicial["disponible"] == 20
    assert inicial["reservado"] == 0

    print("4. Deteniendo transportista...")
    cmd(["docker","compose","stop","transportista-simulator"])
    print("   Transportista: DOWN")

    print("5. Creando pedido afectado...")
    st, alta = http(
        f"{BASE}/pedidos","POST",
        {
            "solicitudId":"E2E14-TRANSPORTISTA-DOWN-001",
            "almacenId":"ALM-01",
            "zonaEntrega":"LIMA_METROPOLITANA",
            "items":[{"sku":"SKU-00002","cantidad":1}]
        },
        token
    )

    pedido = (alta.get("data") or {}).get("pedidoId")
    print(f"   HTTP={st}, pedidoId={pedido}")
    assert st == 202 and pedido

    print("6. Esperando REQUIERE_REVISION...")
    estado = None

    for i in range(1,181):
        st, data = http(f"{BASE}/pedidos/{pedido}",token=token)

        if st == 200:
            estado = (data.get("data") or {}).get("estado")
            if estado in {"REQUIERE_REVISION","DESPACHADO","ANULADO"}:
                print(f"   Estado={estado}, polling={i}")
                break

        time.sleep(0.5)

    if estado != "REQUIERE_REVISION":
        raise RuntimeError(f"Estado esperado REQUIERE_REVISION, obtenido {estado}")

    print("7. Validando Mongo y stock...")

    final = mongo(f'''
const p=db.Pedido.findOne({{_id:"{pedido}"}});
const s=db.Stock.findOne({{IdProducto:"SKU-00002",IdAlmacen:"ALM-01"}});
const g=db.Guia.countDocuments({{IdPedido:"{pedido}"}});
const proc=db.PedidoProceso.find({{IdPedido:"{pedido}"}}).toArray();

print(JSON.stringify({{
 estado:p.IdEstado,
 fechaFinProceso:p.FechaFinProceso,
 pasoPendiente:p.PasoPendiente,
 stockDisponible:s.CantidadStock,
 stockReservado:s.ReservaStock,
 stockTotal:s.CantidadStock+s.ReservaStock,
 guiasMongo:g,
 generarGuia:proc.filter(x=>x.Paso==="GENERAR_GUIA").map(x=>({{
   estado:x.IdEstadoProceso,
   intento:x.NroIntento,
   log:x.Log
 }}))
}}));
''')

    print(json.dumps(final,indent=2,ensure_ascii=False))

    if final["estado"] != "REQUIERE_REVISION":
        raise RuntimeError("Estado Mongo incorrecto")

    if final["fechaFinProceso"] is None:
        raise RuntimeError("Pedido quedó incompleto")

    if (
        final["stockDisponible"] < 0
        or final["stockReservado"] < 0
        or final["stockTotal"] != 20
    ):
        raise RuntimeError("Stock inconsistente")

    if final["guiasMongo"] != 0:
        raise RuntimeError("Se generó guía con transportista caído")

    if len(final["generarGuia"]) == 0:
        raise RuntimeError("No se registró intento GENERAR_GUIA")

    r["pedidoId"] = pedido
    r["final"] = final
    r["resultado"] = "PASS"

    print()
    print("✅ E2E 14: PASS")

except Exception as e:
    r["error"] = str(e)
    print()
    print(f"❌ E2E 14: FAIL - {e}")

with open(EVIDENCIA,"w",encoding="utf-8") as f:
    json.dump(r,f,indent=2,ensure_ascii=False,default=str)

print(f"Evidencia JSON: {EVIDENCIA}")
raise SystemExit(0 if r["resultado"]=="PASS" else 1)
