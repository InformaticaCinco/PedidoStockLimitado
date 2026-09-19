import json
import os
import subprocess
import time
import urllib.error
import urllib.request

JAVA="http://localhost:8090"
MONGO="mongodb://localhost:27017/pedidos_stock?directConnection=true"
EVIDENCIA="tests/evidencias/e2e19-pertenencia.json"

os.makedirs("tests/evidencias",exist_ok=True)

def cmd(args,env=None):
    p=subprocess.run(args,text=True,capture_output=True,env=env)
    if p.returncode!=0:
        raise RuntimeError(f"{' '.join(args)}\n{p.stdout}\n{p.stderr}")
    return p.stdout.strip()

def http(url,method="GET",body=None,token=None):
    h={"Content-Type":"application/json"}
    if token:
        h["Authorization"]=f"Bearer {token}"

    req=urllib.request.Request(
        url,
        data=None if body is None else json.dumps(body).encode(),
        headers=h,
        method=method
    )

    try:
        with urllib.request.urlopen(req,timeout=10) as r:
            raw=r.read().decode()
            return r.status,json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        raw=e.read().decode()
        try:
            return e.code,json.loads(raw)
        except:
            return e.code,{"raw":raw}

def login(usuario):
    st,d=http(
        f"{JAVA}/auth/login","POST",
        {"usuario":usuario,"clave":"Reto2026!"}
    )
    if st!=200:
        raise RuntimeError(f"Login {usuario}: HTTP={st}")
    return d["data"]["accessToken"]

def mongo(js):
    out=cmd([
        "docker","compose","exec","-T","mongodb",
        "mongosh","--quiet",MONGO,"--eval",js
    ])
    return json.loads([x for x in out.splitlines() if x.strip()][-1])

def skus(obj):
    encontrados=set()

    def recorrer(x):
        if isinstance(x,dict):
            for v in x.values():
                recorrer(v)
        elif isinstance(x,list):
            for v in x:
                recorrer(v)
        elif isinstance(x,str):
            if x.startswith("SKU-") and len(x)==9:
                encontrados.add(x)

    recorrer(obj)
    return sorted(encontrados)

r={"escenario":"E2E 19 - Autorizacion por pertenencia","resultado":"FAIL"}

try:
    print("1. Restableciendo entorno...")
    cmd(["docker","compose","down","-v","--remove-orphans"])

    env=os.environ.copy()
    env["FAILURE_RATE"]="0"
    env["PARTIAL_RATE"]="0"

    cmd([
        "docker","compose","up","-d","--no-build",
        "--wait","--wait-timeout","240"
    ],env=env)

    print("   Docker Compose: OK")

    print("2. Login compradores y vendedores...")

    comprador_a=login("comprador01")
    comprador_b=login("comprador02")
    vendedor_a=login("vendedor01")
    vendedor_b=login("vendedor02")

    print("   Logins: OK")

    print("3. Comprador B crea pedido con producto de Vendedor B...")

    st,alta=http(
        f"{JAVA}/pedidos","POST",
        {
            "solicitudId":"E2E19-PEDIDO-B-001",
            "almacenId":"ALM-02",
            "zonaEntrega":"LIMA_METROPOLITANA",
            "items":[
                {"sku":"SKU-00015","cantidad":1}
            ]
        },
        comprador_b
    )

    pedido=(alta.get("data") or {}).get("pedidoId")

    print(f"   HTTP={st}, pedidoId={pedido}")

    if st!=202 or not pedido:
        raise RuntimeError("No se creó pedido de comprador B")

    print("4. Esperando estado terminal...")

    estado=None
    for i in range(120):
        stx,dx=http(
            f"{JAVA}/pedidos/{pedido}",
            token=comprador_b
        )

        if stx==200:
            estado=(dx.get("data") or {}).get("estado")

            if estado in {
                "DESPACHADO",
                "ANULADO",
                "REQUIERE_REVISION"
            }:
                break

        time.sleep(0.5)

    if estado is None:
        raise RuntimeError("Pedido no terminó")

    print(f"   Estado={estado}")

    print("5. Comprador A consulta pedido de Comprador B...")

    st_get,_=http(
        f"{JAVA}/pedidos/{pedido}",
        token=comprador_a
    )

    print(f"   HTTP={st_get}")

    if st_get!=404:
        raise RuntimeError(
            f"Comprador ajeno debía recibir 404, obtuvo {st_get}"
        )

    print("6. Comprador A intenta anular pedido de Comprador B...")

    st_anular,_=http(
        f"{JAVA}/pedidos/{pedido}/anulacion",
        "POST",
        token=comprador_a
    )

    print(f"   HTTP={st_anular}")

    if st_anular!=404:
        raise RuntimeError(
            f"Anulación ajena debía devolver 404, obtuvo {st_anular}"
        )

    print("7. Vendedor A intenta modificar stock de Vendedor B...")

    st_stock,_=http(
        f"{JAVA}/productos/SKU-00015/stock?almacenId=ALM-02",
        "PUT",
        {"disponible":20},
        vendedor_a
    )

    print(f"   HTTP={st_stock}")

    if st_stock!=403:
        raise RuntimeError(
            f"Stock ajeno debía devolver 403, obtuvo {st_stock}"
        )

    print("8. Vendedor A lista pedidos sin ver el pedido de Vendedor B...")

    st_lista,lista=http(
        f"{JAVA}/pedidos?pagina=0",
        token=vendedor_a
    )

    if st_lista!=200:
        raise RuntimeError(f"Listado vendedor A HTTP={st_lista}")

    if pedido in json.dumps(lista):
        raise RuntimeError(
            "Vendedor A vio pedido exclusivo de Vendedor B"
        )

    print("   Pedido ajeno no visible ✅")

    print("9. Preparando pedido con líneas de dos vendedores...")

    fixture=mongo(f'''
const pedido="{pedido}";
const producto=db.Producto.findOne({{_id:"SKU-00002"}});

if (!producto) {{
  print(JSON.stringify({{ok:false,error:"SKU-00002 no existe"}}));
  quit();
}}

const id="DET-E2E19-VENDEDOR-A";

db.PedidoDetalle.updateOne(
  {{_id:id}},
  {{$setOnInsert:{{
    _id:id,
    IdPedidoDetalle:id,
    IdPedido:pedido,
    IdProducto:"SKU-00002",
    IdUsuarioVendedor:producto.IdUsuario,
    Cantidad:1,
    PrecioUnitario:producto.Precio,
    PesoUnitario:producto.Peso,
    Subtotal:producto.Precio,
    UsuarioCreacion:"e2e19",
    FechaCreacion:new Date(),
    UsuarioModificacion:"e2e19",
    FechaModificacion:new Date()
  }}}},
  {{upsert:true}}
);

print(JSON.stringify({{
  ok:true,
  detalles:db.PedidoDetalle.countDocuments({{IdPedido:pedido}})
}}));
''')

    if not fixture.get("ok") or fixture["detalles"]!=2:
        raise RuntimeError(f"Fixture multi-vendedor inválido: {fixture}")

    print("   Pedido con 2 líneas / 2 vendedores ✅")

    print("10. Vendedor A consulta pedido multi-vendedor...")

    st_a,det_a=http(
        f"{JAVA}/pedidos/{pedido}",
        token=vendedor_a
    )

    if st_a!=200:
        raise RuntimeError(
            f"Vendedor A detalle HTTP={st_a}"
        )

    skus_a=skus(det_a.get("data") or {})

    print(f"   SKUs visibles A={skus_a}")

    if skus_a!=["SKU-00002"]:
        raise RuntimeError(
            f"Vendedor A debía ver solo SKU-00002, vio {skus_a}"
        )

    print("11. Vendedor B consulta el mismo pedido...")

    st_b,det_b=http(
        f"{JAVA}/pedidos/{pedido}",
        token=vendedor_b
    )

    if st_b!=200:
        raise RuntimeError(
            f"Vendedor B detalle HTTP={st_b}"
        )

    skus_b=skus(det_b.get("data") or {})

    print(f"   SKUs visibles B={skus_b}")

    if skus_b!=["SKU-00015"]:
        raise RuntimeError(
            f"Vendedor B debía ver solo SKU-00015, vio {skus_b}"
        )

    r["pedidoId"]=pedido
    r["compradorAjenoConsulta"]=st_get
    r["compradorAjenoAnula"]=st_anular
    r["vendedorAjenoStock"]=st_stock
    r["pedidoAjenoOcultoEnListado"]=True
    r["skusVendedorA"]=skus_a
    r["skusVendedorB"]=skus_b
    r["resultado"]="PASS"

    print()
    print("✅ E2E 19: PASS")

except Exception as e:
    r["error"]=str(e)
    print()
    print(f"❌ E2E 19: FAIL - {e}")

with open(EVIDENCIA,"w",encoding="utf-8") as f:
    json.dump(r,f,indent=2,ensure_ascii=False)

print(f"Evidencia JSON: {EVIDENCIA}")
raise SystemExit(0 if r["resultado"]=="PASS" else 1)
