import asyncio
from contextlib import asynccontextmanager, suppress
from http import HTTPStatus
import re
import time
from uuid import uuid4

import httpx
from fastapi import FastAPI, Request, Depends
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse, Response

from app.config import Settings
from app.infrastructure.mongo import Repository
from app.infrastructure.security import Jwks, AuthError
from app.application.worker import Worker
from app.api.upload import receive_file, InputError
from app.logging import event


def envelope(code, message='OK', data=None, errors=None):
    body = dict(code=code, statusCode=f'HTTP_{code}_{HTTPStatus(code).name}', message=message, data=data)
    if errors is not None:
        body['errores'] = errors
    return JSONResponse(body, status_code=code)


def create_app(settings=None, repository=None, security=None, run_worker=True):
    settings = settings or Settings.from_env()
    repo = repository or Repository(settings)
    http = httpx.AsyncClient(timeout=3, follow_redirects=False)
    jwks = security or Jwks(settings, http)

    @asynccontextmanager
    async def lifespan(app):
        task = asyncio.create_task(Worker(repo).run()) if run_worker else None
        try:
            yield
        finally:
            if task:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
            await http.aclose()
            if repository is None:
                await repo.close()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.repo, app.state.jwks = repo, jwks

    @app.middleware('http')
    async def correlation(request, call_next):
        supplied = request.headers.get('X-Correlation-Id', '')
        request.state.correlation = supplied if re.fullmatch(r'[A-Za-z0-9._:-]{1,100}', supplied) else str(uuid4())
        start = time.monotonic()
        try:
            response = await call_next(request)
        except Exception:
            response = envelope(500, 'ERROR_INTERNO')
        response.headers['X-Correlation-Id'] = request.state.correlation
        event('http', correlationId=request.state.correlation, codigo=response.status_code,
              duracionMs=round((time.monotonic() - start) * 1000))
        return response

    @app.exception_handler(InputError)
    async def invalid(request, exc):
        return envelope(exc.status, exc.message)

    @app.exception_handler(AuthError)
    async def auth_error(request, exc):
        return envelope(exc.status, 'NO_AUTENTICADO' if exc.status == 401 else 'NO_AUTORIZADO')

    @app.exception_handler(HTTPException)
    async def http_error(request, exc):
        return envelope(exc.status_code, HTTPStatus(exc.status_code).name)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        return envelope(400, 'ENTRADA_INVALIDA')

    async def admin(request: Request):
        return await jwks.authenticate(request.headers.get('authorization'))

    @app.get('/health')
    async def health():
        return envelope(200, data={'estado': 'UP'})

    @app.get('/health/dependencias')
    async def dependencies():
        async def probe(name, function):
            start = time.monotonic()
            try:
                await function()
                state = 'UP'
            except Exception:
                state = 'DOWN'
            return dict(nombre=name, estado=state, latenciaMs=round((time.monotonic() - start) * 1000))
        checks = await asyncio.gather(probe('MongoDB', repo.ping), probe('JavaJWKS', jwks.fetch))
        if all(c['estado'] == 'UP' for c in checks):
            return envelope(200, data={'dependencias': checks})
        return envelope(503, 'DEPENDENCIAS_NO_DISPONIBLES', errors={'dependencias': checks})

    @app.post('/cargas')
    async def upload(request: Request, actor=Depends(admin)):
        name, content = await receive_file(request, settings.max_upload_bytes)
        await repo.indexes()
        carga_id = await repo.receive(name, content, actor, request.state.correlation)
        return envelope(202, 'CARGA_RECIBIDA', {'cargaId': carga_id})

    async def load(carga_id):
        if not re.fullmatch(r'CG-[A-Za-z0-9-]{1,60}', carga_id):
            raise InputError('CARGA_NO_EXISTE', 404)
        doc = await repo.db.Carga.find_one({'_id': carga_id})
        if doc is None:
            raise InputError('CARGA_NO_EXISTE', 404)
        return doc

    @app.get('/cargas/{carga_id}')
    async def status(carga_id: str, actor=Depends(admin)):
        doc = await load(carga_id)
        counts = await repo.counts(carga_id)
        return envelope(200, data=dict(cargaId=carga_id, estado=doc['IdEstadoProceso'],
            totales=dict(filas=doc['TotalFilas'], aceptadas=counts['CantAceptadas'],
                         rechazadas=counts['CantRechazadas'], duplicadas=counts['CantDuplicadas']),
            reporte=f'/cargas/{carga_id}/reporte' if doc['IdEstadoProceso'] == 'PROCESADA' and doc['ArchivoReporteId'] else None))

    @app.get('/cargas/{carga_id}/reporte')
    async def download(carga_id: str, actor=Depends(admin)):
        doc = await load(carga_id)
        if doc['IdEstadoProceso'] != 'PROCESADA':
            raise InputError('REPORTE_NO_DISPONIBLE', 409)
        try:
            if not doc['ArchivoReporteId']:
                raise RuntimeError('REPORTE_INCONSISTENTE')
            content = await repo.download(doc['ArchivoReporteId'])
        except Exception:
            event('reporte', cargaId=carga_id, resultado='REPORTE_INCONSISTENTE')
            raise
        return Response(content, media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                        headers={'Content-Disposition': f'attachment; filename="reporte-{carga_id}.xlsx"'})

    return app
