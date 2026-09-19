import base64
import json
import os
import subprocess
import tempfile
import time
import urllib.error
import urllib.request

JAVA = "http://localhost:8090"
DOTNET = "http://localhost:8091"
PYTHON = "http://localhost:8092"
EVIDENCIA = "tests/evidencias/e2e17-autenticacion.json"

os.makedirs("tests/evidencias", exist_ok=True)

def http(url, method="GET", body=None, token=None):
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
        with urllib.request.urlopen(req, timeout=10) as r:
            raw=r.read().decode()
            return r.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        raw=e.read().decode()
        try:
            return e.code,json.loads(raw)
        except:
            return e.code,{"raw":raw}

def b64d(v):
    return base64.urlsafe_b64decode(v + "="*(-len(v)%4))

def b64e(v):
    return base64.urlsafe_b64encode(v).decode().rstrip("=")

def encontrar_clave():
    excluir={".git","node_modules",".venv","target","bin","obj","dist"}
    for root,dirs,files in os.walk("."):
        dirs[:]=[d for d in dirs if d not in excluir]
        for f in files:
            path=os.path.join(root,f)
            try:
                data=open(path,"rb").read(10000)
            except:
                continue
            if (
                b"BEGIN PRIVATE KEY" in data
                or b"BEGIN RSA PRIVATE KEY" in data
            ):
                return path
    raise RuntimeError("No se encontró llave privada RSA")

def firmar(token_base, cambios):
    h,p,_=token_base.split(".")
    payload=json.loads(b64d(p))
    payload.update(cambios)

    nuevo_p=b64e(
        json.dumps(payload,separators=(",",":")).encode()
    )
    entrada=f"{h}.{nuevo_p}".encode()

    clave="services/pedidos-java/keys/reto-private.pem"

    with tempfile.NamedTemporaryFile() as fi, \
         tempfile.NamedTemporaryFile() as fo:
        fi.write(entrada)
        fi.flush()

        p=subprocess.run([
            "openssl","dgst","-sha256",
            "-sign",clave,
            "-out",fo.name,
            fi.name
        ],capture_output=True,text=True)

        if p.returncode != 0:
            raise RuntimeError(p.stderr)

        firma=open(fo.name,"rb").read()

    return f"{h}.{nuevo_p}.{b64e(firma)}"

def probar_401(nombre, token):
    pruebas=[
        ("java",f"{JAVA}/pedidos/NO-EXISTE","GET"),
        ("dotnet",f"{DOTNET}/despachos/NO-EXISTE/reintento","POST"),
        ("python",f"{PYTHON}/cargas/NO-EXISTE","GET"),
    ]

    salida={}

    for servicio,url,metodo in pruebas:
        st,_=http(url,metodo,token=token)
        salida[servicio]=st
        if st != 401:
            raise RuntimeError(
                f"{nombre}: {servicio} esperaba 401 y devolvió {st}"
            )

    return salida

r={"escenario":"E2E 17 - Autenticacion","resultado":"FAIL"}

try:
    print("1. Login correcto de los tres perfiles...")

    tokens={}

    for usuario,rol in [
        ("admin","ADMIN"),
        ("vendedor01","VENDEDOR"),
        ("comprador01","COMPRADOR")
    ]:
        st,d=http(
            f"{JAVA}/auth/login","POST",
            {"usuario":usuario,"clave":"Reto2026!"}
        )

        if st != 200:
            raise RuntimeError(f"{usuario}: HTTP={st}")

        data=d.get("data") or {}
        usuario_data=data.get("usuario") or {}

        if usuario_data.get("rol") != rol:
            raise RuntimeError(
                f"{usuario}: rol esperado {rol}, obtenido {usuario_data.get('rol')}"
            )

        tokens[usuario]=data["accessToken"]
        print(f"   {usuario}: 200 / {rol} ✅")

    print("2. Clave incorrecta...")
    st1,d1=http(
        f"{JAVA}/auth/login","POST",
        {"usuario":"comprador01","clave":"CLAVE-INCORRECTA"}
    )
    print(f"   HTTP={st1}")
    if st1 != 401:
        raise RuntimeError("Clave incorrecta no devolvió 401")

    print("3. Usuario inexistente...")
    st2,d2=http(
        f"{JAVA}/auth/login","POST",
        {"usuario":"usuario-que-no-existe","clave":"CLAVE-INCORRECTA"}
    )
    print(f"   HTTP={st2}")

    if st2 != 401:
        raise RuntimeError("Usuario inexistente no devolvió 401")

    msg1=d1.get("message")
    msg2=d2.get("message")

    if msg1 != msg2:
        raise RuntimeError(
            f"Mensajes distintos: {msg1!r} vs {msg2!r}"
        )

    print("   Mismo mensaje ✅")

    print("4. Petición sin token...")
    sin_token={}

    for servicio,url,metodo in [
        ("java",f"{JAVA}/pedidos/NO-EXISTE","GET"),
        ("dotnet",f"{DOTNET}/despachos/NO-EXISTE/reintento","POST"),
        ("python",f"{PYTHON}/cargas/NO-EXISTE","GET")
    ]:
        st,_=http(url,metodo)
        sin_token[servicio]=st
        if st != 401:
            raise RuntimeError(
                f"{servicio} sin token devolvió {st}"
            )

    print(f"   {sin_token} ✅")

    base=tokens["admin"]

    print("5. Token vencido...")
    vencido=firmar(base,{
        "iat":int(time.time())-120,
        "exp":int(time.time())-60
    })
    rv=probar_401("token vencido",vencido)
    print(f"   {rv} ✅")

    print("6. Token con firma alterada...")
    partes=base.split(".")
    firma_bytes=bytearray(b64d(partes[2]))
    firma_bytes[0] ^= 1
    alterado=f"{partes[0]}.{partes[1]}.{b64e(bytes(firma_bytes))}"

    rf=probar_401("firma alterada",alterado)
    print(f"   {rf} ✅")

    print("7. Token válido firmado pero con aud incorrecto...")
    aud_invalido=firmar(base,{
        "aud":"otro-destinatario",
        "iat":int(time.time()),
        "exp":int(time.time())+900
    })

    ra=probar_401("aud incorrecto",aud_invalido)
    print(f"   {ra} ✅")

    r["loginsCorrectos"]=["ADMIN","VENDEDOR","COMPRADOR"]
    r["claveIncorrecta"]=st1
    r["usuarioInexistente"]=st2
    r["mismoMensajeCredenciales"]=True
    r["sinToken"]=sin_token
    r["tokenVencido"]=rv
    r["firmaAlterada"]=rf
    r["audIncorrecto"]=ra
    r["resultado"]="PASS"

    print()
    print("✅ E2E 17: PASS")

except Exception as e:
    r["error"]=str(e)
    print()
    print(f"❌ E2E 17: FAIL - {e}")

with open(EVIDENCIA,"w",encoding="utf-8") as f:
    json.dump(r,f,indent=2,ensure_ascii=False)

print(f"Evidencia JSON: {EVIDENCIA}")
raise SystemExit(0 if r["resultado"]=="PASS" else 1)
