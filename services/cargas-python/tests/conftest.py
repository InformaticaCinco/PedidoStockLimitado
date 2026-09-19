import json
import os
from pathlib import Path
import socket
import subprocess
import time
from uuid import uuid4

import jwt
import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from pymongo import MongoClient
from bson import Decimal128

from app.config import Settings
from app.infrastructure.mongo import Repository
from app.infrastructure.security import Jwks
from app.domain.excel import HEADERS
from openpyxl import Workbook
from io import BytesIO

ROOT = Path(__file__).resolve().parents[1]


def line(solicitud='SOL-001', **changes):
    values = dict(zip(HEADERS, [solicitud, 'CLI-0001', 'ALM-01', 'SKU-00001', 2,
                               'LIMA_METROPOLITANA', '2026-09-18T10:00:00']))
    return values | changes


def excel(lines, headers=HEADERS):
    book = Workbook()
    book.active.append(headers)
    for row in lines:
        book.active.append([row.get(k) for k in headers])
    out = BytesIO()
    book.save(out)
    book.close()
    return out.getvalue()


@pytest.fixture
async def auth():
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private.public_key())) | dict(kid='test-key', alg='RS256', use='sig')
    settings = Settings()
    calls = []
    def jwks_response(request):
        calls.append(request)
        return httpx.Response(200, json=dict(code=200, data={'keys': [public]}))
    async with httpx.AsyncClient(transport=httpx.MockTransport(jwks_response)) as http:
        security = Jwks(settings, http)
        def token(**overrides):
            claims = dict(sub='USR-ADMIN', rol='ADMIN', iss=settings.issuer, aud=settings.audience,
                          exp=int(time.time()) + 300, iat=int(time.time())) | overrides
            claims = {key: value for key, value in claims.items() if value is not None}
            return jwt.encode(claims, private, algorithm='RS256', headers={'kid': public['kid']})
        yield security, token, public, calls


@pytest.fixture(scope='session')
def mongo_uri():
    binary = Path(os.environ.get('MONGODB_TEST_BINARY', ROOT / '../pedidos-java/.build/mongo/mongodb-macos-aarch64-7.0.16/bin/mongod')).resolve()
    if not binary.is_file():
        pytest.fail('MongoDB real obligatorio: configurar MONGODB_TEST_BINARY')
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    folder = ROOT / '.build' / ('mongo-' + uuid4().hex)
    folder.mkdir(parents=True)
    log = (folder / 'process.log').open('w')
    process = subprocess.Popen([str(binary), '--dbpath', str(folder), '--port', str(port),
                                '--bind_ip', '127.0.0.1', '--replSet', 'rsCargas', '--quiet'], stdout=log, stderr=log)
    direct = MongoClient(f'mongodb://127.0.0.1:{port}/?directConnection=true', serverSelectionTimeoutMS=500)
    try:
        for _ in range(60):
            try:
                direct.admin.command('ping')
                break
            except Exception:
                if process.poll() is not None:
                    pytest.fail('Mongo terminó; consultar ' + str(folder))
                time.sleep(.25)
        direct.admin.command('replSetInitiate', {'_id': 'rsCargas', 'members': [{'_id': 0, 'host': f'127.0.0.1:{port}'}]})
        for _ in range(80):
            if direct.admin.command('hello').get('isWritablePrimary'):
                break
            time.sleep(.25)
        else:
            pytest.fail('Replica set sin primary')
        assert direct.server_info()['version'].startswith('7.')
        yield f'mongodb://127.0.0.1:{port}/?replicaSet=rsCargas'
    finally:
        direct.close()
        process.terminate()
        try:
            process.wait(15)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        log.close()


@pytest.fixture
async def repo(mongo_uri):
    settings = Settings(mongo_uri=mongo_uri, database='cargas_it_' + uuid4().hex, retry_base_ms=1)
    repository = Repository(settings)
    await repository.indexes()
    db = repository.db
    await db.Rol.insert_many([{'_id': 'ROL-C', 'Nombre': 'COMPRADOR'}, {'_id': 'ROL-A', 'Nombre': 'ADMIN'}])
    await db.Estado.insert_one({'_id': 'EST-A', 'Nombre': 'ACTIVO'})
    await db.Almacen.insert_many([{'_id': 'ALM-01'}, {'_id': 'ALM-02', 'IdEstado': 'EST-A'}])
    await db.Usuario.insert_many([{'_id': 'USR-C', 'IdRol': 'ROL-C', 'IdEstado': 'ACTIVO'},
                                 {'_id': 'USR-ADMIN', 'IdRol': 'ROL-A'}, {'_id': 'USR-V', 'IdRol': 'ROL-V'}])
    await db.Cliente.insert_one({'_id': 'CLI-0001', 'IdUsuario': 'USR-C'})
    await db.UsuarioAlmacen.insert_one({'_id': 'UA-1', 'IdUsuario': 'USR-V', 'IdAlmacen': 'ALM-01'})
    await db.Producto.insert_many([dict(_id=f'SKU-{i:05d}', SKU=f'SKU-{i:05d}', IdUsuario='USR-V',
                                  Nombre='Test', Precio=Decimal128('10.005'), Peso=Decimal128('1.25')) for i in range(1, 4)])
    await db.Zona.insert_one({'_id': 'ZONA-1', 'Codigo': 'LIMA_METROPOLITANA', 'IdEstado': 'ACTIVO'})
    try:
        yield repository
    finally:
        await repository.client.drop_database(settings.database)
        await repository.close()


@pytest.fixture(autouse=True)
def test_excel_temporaries_stay_local(monkeypatch):
    """Test fixture writers may use openpyxl.save; keep its internals in this module."""
    import tempfile
    from openpyxl.worksheet import _writer
    folder = ROOT / '.build' / 'test-excel-temp'
    folder.mkdir(parents=True, exist_ok=True)
    def local_temp(suffix=''):
        stream = tempfile.NamedTemporaryFile(prefix='openpyxl.', suffix=suffix, dir=folder, delete=False)
        name = stream.name
        stream.close()
        _writer.ALL_TEMP_FILES.append(name)
        return name
    monkeypatch.setattr(_writer, 'create_temporary_file', local_temp)
