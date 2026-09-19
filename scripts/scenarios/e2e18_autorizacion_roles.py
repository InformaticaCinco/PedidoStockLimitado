import json
import os
import subprocess
import urllib.error
import urllib.request

JAVA="http://localhost:8090"
PYTHON="http://localhost:8092"
EVIDENCIA="tests/evidencias/e2e18-autorizacion-roles.json"

os.makedirs("tests/evidencias",exist_ok=True)

def cmd(args, cwd=None, env=None):
    p=subprocess.run(
        args,cwd=cwd,env=env,
        text=True,capture_output=True
    )
    if p.returncode!=0:
        raise RuntimeError(
            f"{' '.join(args)}\n{p.stdout}\n{p.stderr}"
        )
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
        with urllib.request.urlopen(req,timeout=10) as x:
            raw=x.read().decode()
            return x.status,json.loads(raw) if raw else {}
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

r={"escenario":"E2E 18 - Autorizacion por rol","resultado":"FAIL"}

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

    comprador=login("comprador01")
    vendedor=login("vendedor01")

    print("2. COMPRADOR intentando modificar stock...")
    st,_=http(
        f"{JAVA}/productos/SKU-00002/stock?almacenId=ALM-01",
        "PUT",
        {"disponible":20},
        comprador
    )
    print(f"   HTTP={st}")
    if st!=403:
        raise RuntimeError(f"Esperaba 403, obtuvo {st}")

    print("3. VENDEDOR intentando registrar pedido...")
    st2,_=http(
        f"{JAVA}/pedidos",
        "POST",
        {
            "solicitudId":"E2E18-VENDEDOR-001",
            "almacenId":"ALM-01",
            "zonaEntrega":"LIMA_METROPOLITANA",
            "items":[{"sku":"SKU-00002","cantidad":1}]
        },
        vendedor
    )
    print(f"   HTTP={st2}")
    if st2!=403:
        raise RuntimeError(f"Esperaba 403, obtuvo {st2}")

    print("4. COMPRADOR y VENDEDOR intentando API ADMIN...")
    admin403={}

    for nombre,token in [
        ("comprador",comprador),
        ("vendedor",vendedor)
    ]:
        st,_=http(
            f"{PYTHON}/cargas/NO-EXISTE",
            token=token
        )
        admin403[nombre]=st
        print(f"   {nombre}: HTTP={st}")
        if st!=403:
            raise RuntimeError(
                f"{nombre}: esperaba 403 ADMIN, obtuvo {st}"
            )

    print("5. Validando /admin y remoteEntry.js en navegador...")

    out=cmd(
        ["node","tests/e2e18-role.mjs"],
        cwd="frontend/web-host"
    )

    navegador=json.loads(
        [x for x in out.splitlines() if x.strip()][-1]
    )

    print(
        "   comprador remoteEntry="
        f"{navegador['comprador']['remoteEntry']}"
    )
    print(
        "   vendedor remoteEntry="
        f"{navegador['vendedor']['remoteEntry']}"
    )

    if navegador["comprador"]["remoteEntry"]!=0:
        raise RuntimeError(
            "COMPRADOR descargó el microfrontend ADMIN"
        )

    if navegador["vendedor"]["remoteEntry"]!=0:
        raise RuntimeError(
            "VENDEDOR descargó el microfrontend ADMIN"
        )

    r["compradorModificaStock"]=st
    r["vendedorRegistraPedido"]=st2
    r["apiAdmin403"]=admin403
    r["navegador"]=navegador
    r["resultado"]="PASS"

    print()
    print("✅ E2E 18: PASS")

except Exception as e:
    r["error"]=str(e)
    print()
    print(f"❌ E2E 18: FAIL - {e}")

with open(EVIDENCIA,"w",encoding="utf-8") as f:
    json.dump(r,f,indent=2,ensure_ascii=False)

print(f"Evidencia JSON: {EVIDENCIA}")
raise SystemExit(0 if r["resultado"]=="PASS" else 1)
