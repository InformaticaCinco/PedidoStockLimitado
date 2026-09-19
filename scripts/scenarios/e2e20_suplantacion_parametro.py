import json
import os
import subprocess
import time
import urllib.error
import urllib.request

JAVA="http://localhost:8090"
MONGO="mongodb://localhost:27017/pedidos_stock?directConnection=true"
EVIDENCIA="tests/evidencias/e2e20-suplantacion-parametro.json"

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

    data=d["data"]
    return data["accessToken"],data["usuario"]["id"]

def mongo(js):
    out=cmd([
        "docker","compose","exec","-T","mongodb",
        "mongosh","--quiet",MONGO,"--eval",js
    ])
    return json.loads([x for x in out.splitlines() if x.strip()][-1])

r={
    "escenario":"E2E 20 - Suplantacion por parametro",
    "resultado":"FAIL"
}

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

    print("2. Login comprador01 y comprador02...")

    token_a,user_a=login("comprador01")
    _,user_b=login("comprador02")

    clientes=mongo(f'''
const a=db.Cliente.findOne({{IdUsuario:"{user_a}"}});
const b=db.Cliente.findOne({{IdUsuario:"{user_b}"}});

print(JSON.stringify({{
  usuarioA:"{user_a}",
  usuarioB:"{user_b}",
  clienteA:a?._id ?? null,
  clienteB:b?._id ?? null
}}));
''')

    print(json.dumps(clientes,indent=2))

    if not clientes["clienteA"] or not clientes["clienteB"]:
        raise RuntimeError("No se pudo resolver Cliente de los compradores")

    print("3. Comprador01 intenta enviar clienteId de comprador02...")

    solicitud="E2E20-SUPLANTACION-001"

    st,resp=http(
        f"{JAVA}/pedidos",
        "POST",
        {
            "solicitudId":solicitud,
            "clienteId":clientes["clienteB"],
            "almacenId":"ALM-01",
            "zonaEntrega":"LIMA_METROPOLITANA",
            "items":[
                {"sku":"SKU-00002","cantidad":1}
            ]
        },
        token_a
    )

    pedido_id=(resp.get("data") or {}).get("pedidoId")

    print(f"   HTTP={st}, pedidoId={pedido_id}")

    if st == 400:
        print("4. Solicitud rechazada: verificando que no creó pedido...")

        ver=mongo(f'''
const p=db.Pedido.findOne({{IdSolicitud:"{solicitud}"}});

print(JSON.stringify({{
  existe:p!==null
}}));
''')

        if ver["existe"]:
            raise RuntimeError(
                "La solicitud fue rechazada pero creó pedido"
            )

        r["comportamiento"]="RECHAZADO"
        r["http"]=400
        r["pedidoCreado"]=False

    elif st in (200,202):
        if not pedido_id:
            raise RuntimeError("Respuesta aceptada sin pedidoId")

        print("4. Pedido aceptado: verificando identidad persistida...")

        ver=mongo(f'''
const p=db.Pedido.findOne({{_id:"{pedido_id}"}});

print(JSON.stringify({{
  existe:p!==null,
  idCliente:p?.IdCliente ?? null,
  idUsuarioComprador:p?.IdUsuarioComprador ?? null,
  idSolicitud:p?.IdSolicitud ?? null
}}));
''')

        print(json.dumps(ver,indent=2))

        if not ver["existe"]:
            raise RuntimeError("Pedido aceptado no existe en Mongo")

        if ver["idUsuarioComprador"] != user_a:
            raise RuntimeError(
                "Pedido NO quedó asociado al usuario del token"
            )

        if ver["idCliente"] == clientes["clienteB"]:
            raise RuntimeError(
                "SUPLANTACIÓN: pedido quedó a nombre del otro cliente"
            )

        if (
            ver["idCliente"] is not None
            and ver["idCliente"] != clientes["clienteA"]
        ):
            raise RuntimeError(
                f"IdCliente inesperado: {ver['idCliente']}"
            )

        r["comportamiento"]="IGNORADO_Y_USA_TOKEN"
        r["http"]=st
        r["pedidoId"]=pedido_id
        r["persistencia"]=ver

    else:
        raise RuntimeError(
            f"Respuesta no contemplada: HTTP={st}"
        )

    r["usuarioToken"]=user_a
    r["clienteToken"]=clientes["clienteA"]
    r["clienteIntentado"]=clientes["clienteB"]
    r["suplantacionImposible"]=True
    r["resultado"]="PASS"

    print()
    print("✅ E2E 20: PASS")

except Exception as e:
    r["error"]=str(e)

    print()
    print(f"❌ E2E 20: FAIL - {e}")

with open(EVIDENCIA,"w",encoding="utf-8") as f:
    json.dump(r,f,indent=2,ensure_ascii=False)

print(f"Evidencia JSON: {EVIDENCIA}")

raise SystemExit(0 if r["resultado"]=="PASS" else 1)
