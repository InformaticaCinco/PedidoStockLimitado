import json
import os
import subprocess
import urllib.error
import urllib.request

JAVA="http://localhost:8090"
MONGO="mongodb://localhost:27017/pedidos_stock?directConnection=true"
EVIDENCIA="tests/evidencias/e2e21-validacion-seguridad.json"

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

def mongo(js):
    out=cmd([
        "docker","compose","exec","-T","mongodb",
        "mongosh","--quiet",MONGO,"--eval",js
    ])
    return json.loads([x for x in out.splitlines() if x.strip()][-1])

r={"escenario":"E2E 21 - Validacion de entrada y seguridad","resultado":"FAIL"}

try:
    print("1. Restableciendo entorno limpio...")

    cmd(["docker","compose","down","-v","--remove-orphans"])

    env=os.environ.copy()
    env["FAILURE_RATE"]="0"
    env["PARTIAL_RATE"]="0"

    cmd([
        "docker","compose","up","-d","--no-build",
        "--wait","--wait-timeout","240"
    ],env=env)

    print("   Docker Compose: OK")

    print("2. Login comprador01...")

    st,login=http(
        f"{JAVA}/auth/login","POST",
        {"usuario":"comprador01","clave":"Reto2026!"}
    )

    if st!=200:
        raise RuntimeError(f"Login HTTP={st}")

    data=login["data"]
    token=data["accessToken"]
    refresh=data.get("refreshToken")

    print("3. Campo texto con operador MongoDB...")

    st_op,_=http(
        f"{JAVA}/pedidos","POST",
        {
            "solicitudId":{"$ne":"E2E21"},
            "almacenId":"ALM-01",
            "zonaEntrega":"LIMA_METROPOLITANA",
            "items":[
                {"sku":"SKU-00002","cantidad":1}
            ]
        },
        token
    )

    print(f"   HTTP={st_op}")

    if st_op!=400:
        raise RuntimeError(
            f"Operador MongoDB debía devolver 400, obtuvo {st_op}"
        )

    print("4. Cuerpo con tipos incorrectos...")

    st_tipo,_=http(
        f"{JAVA}/pedidos","POST",
        {
            "solicitudId":"E2E21-TIPO-INVALIDO",
            "almacenId":"ALM-01",
            "zonaEntrega":"LIMA_METROPOLITANA",
            "items":[
                {"sku":"SKU-00002","cantidad":"UNO"}
            ]
        },
        token
    )

    print(f"   HTTP={st_tipo}")

    if st_tipo!=400:
        raise RuntimeError(
            f"Tipo incorrecto debía devolver 400, obtuvo {st_tipo}"
        )

    print("5. Verificando claves almacenadas...")

    claves=mongo(r'''
const usuarios=db.Usuario.find({}).toArray();

let textoPlano=false;
let camposClave=[];
let hashes=0;
let sospechosos=[];

for (const u of usuarios) {
  for (const [k,v] of Object.entries(u)) {
    if (/(clave|password|contrasena)/i.test(k)) {
      camposClave.push(k);

      if (v === "Reto2026!") {
        textoPlano=true;
      }

      if (typeof v === "string") {
        if (
          k.toLowerCase().includes("hash") ||
          v.startsWith("$2")
        ) {
          hashes++;
        } else if (v.length > 0) {
          sospechosos.push(k);
        }
      }
    }
  }
}

print(JSON.stringify({
  usuarios:usuarios.length,
  camposClave:[...new Set(camposClave)],
  hashesDetectados:hashes,
  textoPlano:textoPlano,
  camposSospechosos:[...new Set(sospechosos)]
}));
''')

    print(json.dumps(claves,indent=2,ensure_ascii=False))

    if claves["textoPlano"]:
        raise RuntimeError(
            "Se encontró contraseña en texto plano"
        )

    if claves["hashesDetectados"]==0:
        raise RuntimeError(
            "No se detectó almacenamiento de claves con hash"
        )

    print("6. Obteniendo datos personales conocidos para revisar logs...")

    pii=mongo(r'''
const u=db.Usuario.findOne({_id:"USR-COM-001"}) || {};
const c=db.Cliente.findOne({IdUsuario:"USR-COM-001"}) || {};

const valores=[];

for (const d of [u,c]) {
  for (const [k,v] of Object.entries(d)) {
    if (
      /(nombre|apellido|correo|email|telefono|celular|documento|dni|direccion)/i.test(k)
      && typeof v === "string"
      && v.length >= 4
    ) {
      valores.push(v);
    }
  }
}

print(JSON.stringify({
  cantidad:[...new Set(valores)].length,
  valores:[...new Set(valores)]
}));
''')

    print(f"   Valores personales a buscar={pii['cantidad']}")

    print("7. Revisando logs de todos los servicios...")

    logs=cmd([
        "docker","compose","logs","--no-color"
    ])

    prohibidos=[
        ("password","Reto2026!"),
        ("accessToken",token)
    ]

    if refresh:
        prohibidos.append(
            ("refreshToken",refresh)
        )

    for valor in pii["valores"]:
        prohibidos.append(
            ("datoPersonal",valor)
        )

    encontrados=[]

    for tipo,valor in prohibidos:
        if valor and valor in logs:
            encontrados.append(tipo)

    print(
        f"   Credenciales/PII encontrados en logs="
        f"{len(encontrados)}"
    )

    if encontrados:
        raise RuntimeError(
            f"Logs contienen información sensible: {encontrados}"
        )

    if "Reto2026!" in logs:
        raise RuntimeError(
            "Contraseña encontrada en logs"
        )

    if "eyJ" in logs and token in logs:
        raise RuntimeError(
            "JWT encontrado en logs"
        )

    r["operadorMongoHttp"]=st_op
    r["tipoIncorrectoHttp"]=st_tipo
    r["claves"]=claves
    r["piiRevisados"]=pii["cantidad"]
    r["sensiblesEnLogs"]=0
    r["resultado"]="PASS"

    print()
    print("✅ E2E 21: PASS")

except Exception as e:
    r["error"]=str(e)

    print()
    print(f"❌ E2E 21: FAIL - {e}")

with open(EVIDENCIA,"w",encoding="utf-8") as f:
    json.dump(r,f,indent=2,ensure_ascii=False)

print(f"Evidencia JSON: {EVIDENCIA}")

raise SystemExit(0 if r["resultado"]=="PASS" else 1)
