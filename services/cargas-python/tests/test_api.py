from types import SimpleNamespace
from unittest.mock import AsyncMock
import time
import jwt
import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app.api.http import create_app
from app.config import Settings
from app.infrastructure.security import AuthError
from tests.conftest import excel, line


@pytest.fixture
async def api(auth):
    security, token, _, _ = auth
    repo = SimpleNamespace(ping=AsyncMock(), indexes=AsyncMock(), receive=AsyncMock(return_value='CG-test'))
    app = create_app(Settings(max_upload_bytes=6000), repository=repo, security=security, run_worker=False)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            yield client, token, repo


async def test_health_and_dependencies(api):
    client, _, repo = api
    result = await client.get('/health', headers={'X-Correlation-Id': 'smoke-valid'})
    assert result.status_code == 200 and result.json()['data'] == {'estado': 'UP'}
    assert result.headers['X-Correlation-Id'] == 'smoke-valid'
    assert (await client.get('/health/dependencias')).status_code == 200
    repo.ping.side_effect = RuntimeError('secret')
    result = await client.get('/health/dependencias')
    assert result.status_code == 503 and result.json()['data'] is None
    assert 'secret' not in result.text
    assert (await client.get('/health')).status_code == 200


@pytest.mark.parametrize('claims,status', [(None, 401), ({'rol': 'COMPRADOR'}, 403), ({'rol': 'VENDEDOR'}, 403),
    ({'exp': 1}, 401), ({'iss': 'other'}, 401), ({'aud': 'other'}, 401), ({'sub': ''}, 401)])
async def test_auth(api, claims, status):
    client, token, repo = api
    headers = {'Authorization': 'Bearer ' + token(**claims)} if claims is not None else {'X-Role': 'ADMIN', 'X-User-Id': 'spoof'}
    for path in ['/cargas', '/cargas/CG-test', '/cargas/CG-test/reporte']:
        result = await (client.post(path, headers=headers) if path == '/cargas' else client.get(path, headers=headers))
        assert result.status_code == status and result.json()['data'] is None
    repo.receive.assert_not_called()


async def test_bad_signature_and_jwks_rotation(auth):
    security, token, public, calls = auth
    wrong = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    claims = jwt.decode(token(), options={'verify_signature': False})
    bad = jwt.encode(claims, wrong, algorithm='RS256', headers={'kid': public['kid']})
    with pytest.raises(AuthError):
        await security.authenticate('Bearer ' + bad)
    assert await security.authenticate('Bearer ' + token()) == 'USR-ADMIN'
    assert len(calls) == 1
    public['kid'] = 'rotated'
    assert await security.authenticate('Bearer ' + token()) == 'USR-ADMIN'
    assert len(calls) == 2


@pytest.mark.parametrize('files,status', [([], 400), ([('archivo', ('file.csv', b'x'))], 400),
    ([('archivo', ('file.xlsx', b''))], 400), ([('archivo', ('../file.xlsx', b'x'))], 400),
    ([('archivo', ('file.xlsx', b'x'*6001))], 413),
    ([('archivo', ('file.xlsx', b'x')), ('extra', ('file.xlsx', b'x'))], 400),
    ([('other', ('file.xlsx', b'x'))], 400)])
async def test_bad_upload(api, files, status):
    client, token, repo = api
    result = await client.post('/cargas', files=files, headers={'Authorization': 'Bearer ' + token()})
    assert result.status_code == status
    repo.receive.assert_not_called()


async def test_accept_persists_actor_not_spoof_and_does_not_parse(api):
    client, token, repo = api
    result = await client.post('/cargas', files={'archivo': ('file.xlsx', b'not-a-workbook')},
       headers={'Authorization': 'Bearer ' + token(), 'X-User-Id': 'spoof', 'X-Correlation-Id': 'trace-1'})
    assert result.status_code == 202 and result.json()['data'] == {'cargaId': 'CG-test'}
    repo.receive.assert_awaited_once_with('file.xlsx', b'not-a-workbook', 'USR-ADMIN', 'trace-1')


async def test_extra_field_and_generic_error(api):
    client, token, repo = api
    headers = {'Authorization': 'Bearer ' + token()}
    result = await client.post('/cargas', files={'archivo': ('file.xlsx', b'x')}, data={'user': 'spoof'}, headers=headers)
    assert result.status_code == 400
    repo.receive.side_effect = RuntimeError('private trace')
    result = await client.post('/cargas', files={'archivo': ('file.xlsx', b'x')}, headers=headers)
    assert result.status_code == 500 and 'private' not in result.text


async def test_invalid_jwks_and_missing_expiration(auth):
    security, token, _, _ = auth
    with pytest.raises(AuthError):
        await security.authenticate('Bearer ' + token(exp=None))
    security.loaded = 0
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={'keys': []}))) as bad:
        security.http = bad
        with pytest.raises(AuthError):
            await security.authenticate('Bearer ' + token())


async def test_malformed_multipart_and_correlation(api):
    client, token, repo = api
    headers = {'Authorization': 'Bearer ' + token(), 'Content-Type': 'multipart/form-data; boundary=abc', 'X-Correlation-Id': 'bad value'}
    response = await client.post('/cargas', content=b'--abc\r\nnot closed', headers=headers)
    assert response.status_code == 400
    assert response.headers['X-Correlation-Id'] != 'bad value'
    repo.receive.assert_not_called()
