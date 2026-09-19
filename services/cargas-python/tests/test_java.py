"""Lectura e idempotencia HTTP reales con el JAR existente, sin escribir en Java."""
import asyncio
from dataclasses import replace
import os
from pathlib import Path
import socket
import subprocess

import httpx
import pytest

from app.api.http import create_app
from app.infrastructure.security import Jwks
from app.application.worker import Worker
from tests.conftest import ROOT, line, excel

pytestmark = pytest.mark.mongo


async def test_real_java_login_jwks_import_read_and_cross_idempotency(repo):
    java = Path(os.environ.get('JAVA_TEST_BINARY', '/Library/Java/JavaVirtualMachines/temurin-21.jdk/Contents/Home/bin/java'))
    jar = (ROOT / '../pedidos-java/target/pedidos-1.0.0.jar').resolve()
    keys = (ROOT / '../pedidos-java/keys').resolve()
    helper = ROOT / '.build' / 'HashPassword.java'
    helper.write_text('import org.mindrot.jbcrypt.BCrypt; class HashPassword { public static void main(String[] args) { System.out.print(BCrypt.hashpw("clave-it", BCrypt.gensalt(4))); }}')
    result = await asyncio.to_thread(subprocess.run, [str(java), '--class-path', str(jar), str(helper)], capture_output=True, text=True, check=True)
    password_hash = result.stdout.strip()
    for user, login in [('USR-ADMIN', 'admin-it'), ('USR-C', 'comprador-it'), ('USR-V', 'vendedor-it')]:
        await repo.db.Usuario.update_one({'_id': user}, {'$set': {'Usuario': login, 'Nombre': 'Test', 'ClaveHash': password_hash}})
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    settings = replace(repo.settings, jwks_url=f'http://127.0.0.1:{port}/.well-known/jwks.json')
    env = os.environ | dict(PORT=str(port), MONGODB_URI=repo.settings.mongo_uri,
        MONGODB_DATABASE=repo.settings.database, JWT_PRIVATE_KEY_PATH=str(keys / 'reto-private.pem'),
        JWT_PUBLIC_KEY_PATH=str(keys / 'reto-public.pem'), JWT_ISSUER=settings.issuer, JWT_AUDIENCE=settings.audience)
    with (ROOT / '.build' / 'java-real.log').open('w') as log:
        process = subprocess.Popen([str(java), '-jar', str(jar)], cwd=ROOT, env=env, stdout=log, stderr=log)
        try:
            async with httpx.AsyncClient(base_url=f'http://127.0.0.1:{port}', timeout=5) as java_http:
                for _ in range(100):
                    try:
                        if (await java_http.get('/health')).status_code == 200:
                            break
                    except httpx.RequestError:
                        pass
                    assert process.poll() is None, 'Java terminó: .build/java-real.log'
                    await asyncio.sleep(.1)
                else:
                    pytest.fail('Java no arrancó')
                async def login(name):
                    response = await java_http.post('/auth/login', json={'usuario': name, 'clave': 'clave-it'})
                    assert response.status_code == 200, response.text
                    return response.json()['data']['accessToken']
                admin_token, buyer_token = await login('admin-it'), await login('comprador-it')
                security = Jwks(settings, java_http)
                app = create_app(settings, repo, security, run_worker=False)
                async with app.router.lifespan_context(app), httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://python') as api:
                    uploaded = await api.post('/cargas', files={'archivo': ('real.xlsx', excel([line()]))},
                                             headers={'Authorization': 'Bearer ' + admin_token})
                    assert uploaded.status_code == 202, uploaded.text
                    assert await Worker(repo).once()
                    pedido = await repo.db.Pedido.find_one({'IdSolicitud': 'SOL-001'})
                    buyer_headers = {'Authorization': 'Bearer ' + buyer_token}
                    viewed = await java_http.get('/pedidos/' + pedido['_id'], headers=buyer_headers)
                    assert viewed.status_code == 200, viewed.text
                    assert viewed.json()['data']['items'][0]['sku'] == 'SKU-00001'
                    request = dict(solicitudId='SOL-001', almacenId='ALM-01', zonaEntrega='LIMA_METROPOLITANA', items=[{'sku': 'SKU-00001', 'cantidad': 2}])
                    repeated = await java_http.post('/pedidos', json=request, headers=buyer_headers)
                    assert repeated.status_code == 200 and repeated.json()['data']['pedidoId'] == pedido['_id']
                    request['items'][0]['cantidad'] = 3
                    assert (await java_http.post('/pedidos', json=request, headers=buyer_headers)).status_code == 409
                    # Opposite direction: Java first, then Python detects duplicate.
                    await repo.db.Stock.insert_one(dict(_id='STK-1', IdAlmacen='ALM-01', IdProducto='SKU-00001', CantidadStock=0, ReservaStock=0))
                    request['solicitudId'] = 'JAVA-FIRST'
                    request['items'][0]['cantidad'] = 2
                    created = await java_http.post('/pedidos', json=request, headers=buyer_headers)
                    assert created.status_code == 202, created.text
                    carga_id = await repo.receive('again.xlsx', excel([line('JAVA-FIRST')]), 'USR-ADMIN', 'java-real')
                    assert await Worker(repo).once()
                    assert (await repo.db.Carga.find_one({'_id': carga_id}))['CantDuplicadas'] == 1
                    assert await repo.db.Pedido.count_documents({}) == 2
                    assert (await repo.db.Stock.find_one({}))['CantidadStock'] == 0
        finally:
            process.terminate()
            try:
                await asyncio.to_thread(process.wait, 15)
            except subprocess.TimeoutExpired:
                process.kill()
                await asyncio.to_thread(process.wait)
