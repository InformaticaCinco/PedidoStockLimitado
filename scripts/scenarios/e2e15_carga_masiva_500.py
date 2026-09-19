import json
import os
import subprocess
import time
import urllib.error
import urllib.request
import zipfile
import xml.etree.ElementTree as ET

JAVA = "http://localhost:8080/api/java"
CARGAS = "http://localhost:8092"
MONGO = "mongodb://localhost:27017/pedidos_stock?directConnection=true"

XLSX = "datos/pedidos-masivo.xlsx"
REPORTE = "tests/evidencias/e2e15-reporte.xlsx"
EVIDENCIA = "tests/evidencias/e2e15-carga-masiva-500.json"

os.makedirs("tests/evidencias", exist_ok=True)

def cmd(args, env=None):
    p = subprocess.run(args, text=True, capture_output=True, env=env)
    if p.returncode != 0:
        raise RuntimeError(f"{' '.join(args)}\n{p.stdout}\n{p.stderr}")
    return p.stdout.strip()

def http_json(url, method="GET", body=None, token=None, timeout=20):
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
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode()
            return r.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, {"raw": raw}

def mongo(js):
    out = cmd([
        "docker","compose","exec","-T","mongodb",
        "mongosh","--quiet",MONGO,"--eval",js
    ])
    lines = [x.strip() for x in out.splitlines() if x.strip()]
    return json.loads(lines[-1])

def filas_xlsx(path):
    with zipfile.ZipFile(path) as z:
        xml = z.read("xl/worksheets/sheet1.xml")
    root = ET.fromstring(xml)
    ns = {"m":"http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    return len(root.findall(".//m:sheetData/m:row", ns))

r = {"escenario":"E2E 15 - Carga masiva 500 filas","resultado":"FAIL"}

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

    print("2. Validando archivo Excel...")

    if not os.path.exists(XLSX):
        raise RuntimeError(f"No existe {XLSX}")

    filas = filas_xlsx(XLSX) - 1
    print(f"   Filas de datos={filas}")

    if filas != 500:
        raise RuntimeError(f"Se esperaban 500 filas, existen {filas}")

    print("3. Login ADMIN...")

    st, login = http_json(
        f"{JAVA}/auth/login",
        "POST",
        {"usuario":"admin","clave":"Reto2026!"}
    )

    if st != 200:
        raise RuntimeError(f"Login ADMIN HTTP={st}")

    token = login["data"]["accessToken"]

    print("4. Subiendo pedidos-masivo.xlsx...")

    p = subprocess.run([
        "curl","-sS",
        "-X","POST",
        f"{CARGAS}/cargas",
        "-H",f"Authorization: Bearer {token}",
        "-F",f"archivo=@{XLSX};type=application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "-w","\n%{http_code}"
    ], text=True, capture_output=True)

    if p.returncode != 0:
        raise RuntimeError(p.stderr)

    partes = p.stdout.rstrip().rsplit("\n",1)
    body = json.loads(partes[0])
    status = int(partes[1])

    data = body.get("data") or body
    carga_id = data.get("cargaId")

    print(f"   HTTP={status}, cargaId={carga_id}")

    if status != 202 or not carga_id:
        raise RuntimeError(f"POST /cargas inválido: {body}")

    r["cargaId"] = carga_id

    print("5. Esperando procesamiento del Excel...")

    resumen = None

    for i in range(1,601):
        st, resp = http_json(
            f"{CARGAS}/cargas/{carga_id}",
            token=token,
            timeout=5
        )

        if st == 200:
            d = resp.get("data") or resp
            estado = d.get("estado")

            if estado == "PROCESADA":
                resumen = d
                print(f"   PROCESADA, polling={i}")
                break

            if estado == "ERROR":
                raise RuntimeError(f"Carga terminó ERROR: {d}")

        time.sleep(0.5)

    if resumen is None:
        raise RuntimeError("Timeout esperando carga PROCESADA")

    tot = resumen.get("totales") or {}

    print(json.dumps(tot, indent=2, ensure_ascii=False))

    if tot.get("filas") != 500:
        raise RuntimeError("Total filas distinto de 500")

    suma = (
        int(tot.get("aceptadas",0))
        + int(tot.get("rechazadas",0))
        + int(tot.get("duplicadas",0))
    )

    if suma != 500:
        raise RuntimeError(f"Contadores no suman 500: {suma}")

    if int(tot.get("rechazadas",0)) == 0:
        raise RuntimeError("No existen filas rechazadas")

    if int(tot.get("duplicadas",0)) == 0:
        raise RuntimeError("No existen filas duplicadas")

    r["totales"] = tot

    print("6. Descargando reporte XLSX...")

    req = urllib.request.Request(
        f"{CARGAS}/cargas/{carga_id}/reporte",
        headers={"Authorization":f"Bearer {token}"}
    )

    with urllib.request.urlopen(req, timeout=30) as resp:
        contenido = resp.read()
        status_rep = resp.status
        content_type = resp.headers.get("Content-Type","")

    if status_rep != 200:
        raise RuntimeError(f"Reporte HTTP={status_rep}")

    with open(REPORTE,"wb") as f:
        f.write(contenido)

    filas_reporte = filas_xlsx(REPORTE) - 1

    print(
        f"   HTTP=200, filas reporte={filas_reporte}, "
        f"bytes={len(contenido)}"
    )

    if filas_reporte != 500:
        raise RuntimeError(
            f"Reporte debe tener 500 filas, tiene {filas_reporte}"
        )

    r["reporte"] = {
        "archivo": REPORTE,
        "filas": filas_reporte,
        "bytes": len(contenido),
        "contentType": content_type
    }

    print("7. Identificando los 20 pedidos de últimas 3 unidades...")

    crit = mongo(f'''
const idsCarga = db.CargaDetalle.distinct(
  "IdPedido",
  {{
    IdCarga:"{carga_id}",
    IdPedido:{{$type:"string"}}
  }}
);

const criticos = db.PedidoDetalle.distinct(
  "IdPedido",
  {{
    IdPedido:{{$in:idsCarga}},
    IdProducto:"SKU-00001"
  }}
);

print(JSON.stringify({{
  pedidosCarga:idsCarga.length,
  pedidosCriticos:criticos.length,
  ids:criticos
}}));
''')

    print(
        f"   Pedidos críticos encontrados="
        f"{crit['pedidosCriticos']}"
    )

    if crit["pedidosCriticos"] != 20:
        raise RuntimeError(
            f"Se esperaban 20 pedidos críticos, "
            f"se encontraron {crit['pedidosCriticos']}"
        )

    ids_json = json.dumps(crit["ids"])

    print("8. Esperando estado terminal de los 20 pedidos críticos...")

    final = None

    for i in range(1,1201):
        dato = mongo(f'''
const ids={ids_json};
const docs=db.Pedido.find({{_id:{{$in:ids}}}}).toArray();

const conteo={{}};
for (const p of docs) {{
  conteo[p.IdEstado]=(conteo[p.IdEstado]||0)+1;
}}

const terminales=docs.filter(p =>
  ["DESPACHADO","ANULADO","REQUIERE_REVISION"]
  .includes(p.IdEstado)
).length;

const stock=db.Stock.findOne({{
  IdProducto:"SKU-00001",
  IdAlmacen:"ALM-01"
}});

print(JSON.stringify({{
  total:docs.length,
  terminales:terminales,
  estados:conteo,
  disponible:stock.CantidadStock,
  reservado:stock.ReservaStock,
  guiasActivas:db.Guia.countDocuments({{
    IdPedido:{{$in:ids}},
    IdEstado:"ACTIVO"
  }})
}}));
''')

        if dato["terminales"] == 20:
            final = dato
            print(f"   Todos terminales, polling={i}")
            break

        time.sleep(0.5)

    if final is None:
        raise RuntimeError(
            "Los 20 pedidos críticos no terminaron"
        )

    print(json.dumps(final, indent=2, ensure_ascii=False))

    despachados = int(final["estados"].get("DESPACHADO",0))

    if despachados != 3:
        raise RuntimeError(
            f"Se esperaban exactamente 3 DESPACHADO, "
            f"se obtuvieron {despachados}"
        )

    if final["disponible"] != 0:
        raise RuntimeError(
            f"Stock disponible esperado 0, obtenido {final['disponible']}"
        )

    if final["reservado"] != 0:
        raise RuntimeError(
            f"Stock reservado esperado 0, obtenido {final['reservado']}"
        )

    if final["guiasActivas"] != 3:
        raise RuntimeError(
            f"Se esperaban 3 guías activas, "
            f"se obtuvieron {final['guiasActivas']}"
        )

    r["criticos"] = final
    r["resultado"] = "PASS"

    print()
    print("✅ E2E 15: PASS")

except Exception as e:
    r["error"] = str(e)
    print()
    print(f"❌ E2E 15: FAIL - {e}")

with open(EVIDENCIA,"w",encoding="utf-8") as f:
    json.dump(
        r,f,indent=2,
        ensure_ascii=False,
        default=str
    )

print(f"Evidencia JSON: {EVIDENCIA}")

raise SystemExit(0 if r["resultado"]=="PASS" else 1)
