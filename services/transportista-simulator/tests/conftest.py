from contextlib import asynccontextmanager
from dataclasses import dataclass

import pytest
from aiohttp import ClientSession, web

from app.main import Config, STATE, create_app


@dataclass
class Servidor:
    app: web.Application
    url: str
    client: ClientSession

    @property
    def state(self):
        return self.app[STATE]

    async def post(self, key="clave-1", body=None, **kwargs):
        if body is None:
            body = {"pedidoId": "PED-001", "pesoKg": 12.4, "zona": "PROVINCIA"}
        return await self.client.post(self.url + "/guias", json=body,
                                      headers={"Idempotency-Key": key}, **kwargs)

    async def get(self, pedido="PED-001"):
        return await self.client.get(self.url + "/guias", params={"pedidoId": pedido})


@pytest.fixture
def servidor():
    @asynccontextmanager
    async def abrir(config=None, azar=None):
        app = create_app(config or Config(failure_rate=0, partial_rate=0, latency_ms=20), azar=azar)
        runner = web.AppRunner(app, access_log=None)
        await runner.setup()
        try:
            site = web.TCPSite(runner, "127.0.0.1", 0)
            await site.start()
            url = f"http://127.0.0.1:{runner.addresses[0][1]}"
            async with ClientSession() as client:
                yield Servidor(app, url, client)
        finally:
            await runner.cleanup()
    return abrir
