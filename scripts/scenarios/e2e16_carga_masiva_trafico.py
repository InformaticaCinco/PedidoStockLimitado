import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

JAVA = "http://localhost:8080/api/java"
CARGAS = "http://localhost:8092"
MONGO = "mongodb://localhost:27017/pedidos_stock?directConnection=true"
XLSX = "datos/pedidos-masivo.xlsx"
EVIDENCIA = "tests/evidencias/e2e16-carga-masiva-trafico.json"

os.makedirs("tests/evidencias", exist_ok=True)

def cmd(args, env=None):
    p = subprocess.run(args, text=True, capture_output=True, env=env)
    if p.returncode != 0:
        raise RuntimeError(f"{' '.join(args)}\n{p.stdout}\n{p.stderr}")
    return p.stdout.strip()

def http(url, method="GET", body=None, token=None, timeout=20):
    h = {"Content-Type":"application/json"}
    if token:
        h["Authorization"] = f"Bearer {token}"

    req = urllib.request.Request(
        url,
        data=None if body is None else json.dumps(body).encode(),
        headers=h,
        method=method
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
            return e.code, {"raw":raw}

def mongo(js):
    out = cmd([
        "docker","compose","exec","-T","mongodb",
        "mongosh","--quiet",MONGO,"--eval",js
    ])
    return json.loads([x for x in out.splitlines() if x.strip()][-1])

r = {"escenario":"E2E 16 - Carga masiva con trafico simultaneo","resultado":"FAIL"}

try:
    print("1. Restableciendo entorno limpio...")
    cmd(["docker","compose","down","-v","--remove-orphans"])

    env = os.environ.copy()
    env["FAILURE_RATE"] = "0"
    env["PARTIAL_RATE"] = "0"

    cmd([
        "docker","compose","up","-d","--no-build",
        "--wait","--wait-timeout","240"
    ], env=env)
    print("   Docker Compose: OK")

    print("2. Login ADMIN + 20 compradores...")

    st, a = http(
        f"{JAVA}/auth/login","POST",
        {"usuario":"admin","clave":"Reto2026!"}
    )
    assert st == 200
    admin = a["data"]["accessToken"]

    tokens = []

    for i in range(1,21):
        st, d = http(
            f"{JAVA}/auth/login","POST",
            {"usuario":f"comprador{i:02d}","clave":"Reto2026!"}
        )
        if st != 200:
            raise RuntimeError(f"Login comprador{i:02d} HTTP={st}")
        tokens.append(d["data"]["accessToken"])

    print("   Logins: OK")

    stock0 = mongo('''
const s=db.Stock.findOne({
  IdProducto:"SKU-00001",
  IdAlmacen:"ALM-01"
});
print(JSON.stringify({
 disponible:s.CantidadStock,
 reservado:s.ReservaStock
}));
''')

    print(f"3. Stock inicial SKU-00001 = {stock0['disponible']} / {stock0['reservado']}")

    if stock0 != {"disponible":3,"reservado":0}:
        raise RuntimeError("Stock inicial esperado 3 / 0")

    print("4. Iniciando carga masiva de 500 filas...")

    p = subprocess.run([
        "curl","-sS","-X","POST",
        f"{CARGAS}/cargas",
        "-H",f"Authorization: Bearer {admin}",
        "-F",f"archivo=@{XLSX};type=application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "-w","\n%{http_code}"
    ], text=True, capture_output=True)

    body, code = p.stdout.rstrip().rsplit("\n",1)
    resp = json.loads(body)
    carga_id = (resp.get("data") or resp).get("cargaId")

    print(f"   HTTP={code}, cargaId={carga_id}")

    if int(code) != 202 or not carga_id:
        raise RuntimeError("No inició carga")

    print("5. Lanzando inmediatamente 20 pedidos individuales simultáneos...")

    def crear(i):
        st, d = http(
            f"{JAVA}/pedidos","POST",
            {
                "solicitudId":f"E2E16-IND-{i:03d}",
                "almacenId":"ALM-01",
                "zonaEntrega":"LIMA_METROPOLITANA",
                "items":[{"sku":"SKU-00001","cantidad":1}]
            },
            tokens[i-1]
        )
        return i, st, (d.get("data") or {}).get("pedidoId")

    respuestas = []

    with ThreadPoolExecutor(max_workers=20) as ex:
        fs = [ex.submit(crear,i) for i in range(1,21)]
        for f in as_completed(fs):
            respuestas.append(f.result())

    codigos = {}
    pedidos_ind = []

    for _, st, pid in respuestas:
        codigos[str(st)] = codigos.get(str(st),0)+1
        if pid:
            pedidos_ind.append(pid)

    print(f"   HTTP pedidos={codigos}, pedidoIds={len(pedidos_ind)}")

    if len(pedidos_ind) != 20:
        raise RuntimeError("No se crearon los 20 pedidos individuales")

    print("6. Esperando carga PROCESADA...")

    resumen = None
    for i in range(1,601):
        st, d = http(f"{CARGAS}/cargas/{carga_id}",token=admin,timeout=5)
        if st == 200:
            data = d.get("data") or d
            if data.get("estado") == "PROCESADA":
                resumen = data
                print(f"   PROCESADA, polling={i}")
                break
            if data.get("estado") == "ERROR":
                raise RuntimeError("Carga terminó ERROR")
        time.sleep(0.5)

    if resumen is None:
        raise RuntimeError("Timeout de carga")

    print("7. Identificando los 20 pedidos críticos del Excel...")

    crit = mongo(f'''
const idsCarga=db.CargaDetalle.distinct(
 "IdPedido",
 {{IdCarga:"{carga_id}",IdPedido:{{$type:"string"}}}}
);

const ids=db.PedidoDetalle.distinct(
 "IdPedido",
 {{IdPedido:{{$in:idsCarga}},IdProducto:"SKU-00001"}}
);

print(JSON.stringify({{
 total:ids.length,
 ids:ids
}}));
''')

    print(f"   Pedidos Excel críticos={crit['total']}")

    if crit["total"] != 20:
        raise RuntimeError("Se esperaban 20 pedidos críticos del Excel")

    todos = list(dict.fromkeys(crit["ids"] + pedidos_ind))

    if len(todos) != 40:
        raise RuntimeError(f"Se esperaban 40 pedidos competidores, hay {len(todos)}")

    ids_js = json.dumps(todos)

    print("8. Esperando los 40 pedidos terminales...")

    final = None
    minimo_disponible = 3
    minimo_reservado = 0

    for i in range(1,1201):
        dato = mongo(f'''
const ids={ids_js};
const ps=db.Pedido.find({{_id:{{$in:ids}}}}).toArray();
const s=db.Stock.findOne({{
 IdProducto:"SKU-00001",
 IdAlmacen:"ALM-01"
}});

const estados={{}};
for (const p of ps)
 estados[p.IdEstado]=(estados[p.IdEstado]||0)+1;

const terminales=ps.filter(x =>
 ["DESPACHADO","ANULADO","REQUIERE_REVISION"].includes(x.IdEstado)
).length;

print(JSON.stringify({{
 total:ps.length,
 terminales:terminales,
 estados:estados,
 disponible:s.CantidadStock,
 reservado:s.ReservaStock,
 guiasActivas:db.Guia.countDocuments({{
   IdPedido:{{$in:ids}},
   IdEstado:"ACTIVO"
 }})
}}));
''')

        minimo_disponible = min(minimo_disponible,dato["disponible"])
        minimo_reservado = min(minimo_reservado,dato["reservado"])

        if dato["disponible"] < 0 or dato["reservado"] < 0:
            raise RuntimeError("Se observó stock negativo")

        if dato["terminales"] == 40:
            final = dato
            print(f"   Terminales=40, polling={i}")
            break

        time.sleep(0.25)

    if final is None:
        raise RuntimeError("Los 40 pedidos no terminaron")

    print(json.dumps(final,indent=2,ensure_ascii=False))

    despachados = int(final["estados"].get("DESPACHADO",0))

    if despachados > 3:
        raise RuntimeError(f"OVERSELL: {despachados} despachos para stock 3")

    if despachados != 3:
        raise RuntimeError(f"Esperábamos 3 despachos efectivos, obtuvo {despachados}")

    if final["disponible"] != 0 or final["reservado"] != 0:
        raise RuntimeError("Stock final inconsistente")

    if final["guiasActivas"] != 3:
        raise RuntimeError("Cantidad de guías activas inconsistente")

    r["cargaId"] = carga_id
    r["pedidosExcel"] = 20
    r["pedidosIndividuales"] = 20
    r["competidores"] = 40
    r["respuestasIndividuales"] = codigos
    r["final"] = final
    r["sinOversell"] = True
    r["resultado"] = "PASS"

    print()
    print("✅ E2E 16: PASS")

except Exception as e:
    r["error"] = str(e)
    print()
    print(f"❌ E2E 16: FAIL - {e}")

with open(EVIDENCIA,"w",encoding="utf-8") as f:
    json.dump(r,f,indent=2,ensure_ascii=False,default=str)

print(f"Evidencia JSON: {EVIDENCIA}")
raise SystemExit(0 if r["resultado"]=="PASS" else 1)
