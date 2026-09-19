import asyncio
import os

from aiohttp import ClientSession, ClientTimeout, web

TARGET_URL = os.getenv(
    "TARGET_URL",
    "http://transportista-simulator:9090"
).rstrip("/")

DELAY_SECONDS = float(
    os.getenv("DELAY_SECONDS", "2.5")
)

estado = {
    "guiaCreada": False,
    "pedidoId": None,
    "statusTransportista": None,
    "postGuiasInterceptados": 0
}


async def startup(app):
    app["session"] = ClientSession(
        timeout=ClientTimeout(total=15)
    )


async def cleanup(app):
    await app["session"].close()


async def test_health(request):
    return web.json_response({
        "estado": "UP"
    })


async def test_status(request):
    return web.json_response(estado)


async def proxy(request):
    target = TARGET_URL + request.rel_url.path_qs
    body = await request.read()

    headers = {}

    for nombre in (
        "Content-Type",
        "Idempotency-Key",
        "X-Correlation-Id"
    ):
        valor = request.headers.get(nombre)
        if valor:
            headers[nombre] = valor

    async with request.app["session"].request(
        request.method,
        target,
        data=body if body else None,
        headers=headers
    ) as response:
        raw = await response.read()
        status = response.status
        content_type = response.headers.get(
            "Content-Type",
            "application/json"
        )

    # Solo retenemos la creación de guía.
    # En este punto el transportista REAL ya registró la guía.
    if (
        request.method == "POST"
        and request.path == "/guias"
        and status in (200, 201)
    ):
        estado["guiaCreada"] = True
        estado["statusTransportista"] = status
        estado["postGuiasInterceptados"] += 1

        try:
            payload = await request.json()
            estado["pedidoId"] = payload.get("pedidoId")
        except Exception:
            pass

        print(
            f"E2E09_GUIA_CREADA "
            f"pedidoId={estado['pedidoId']} "
            f"status={status}",
            flush=True
        )

        # Ventana controlada para solicitar anulación.
        await asyncio.sleep(DELAY_SECONDS)

    return web.Response(
        status=status,
        body=raw,
        headers={
            "Content-Type": content_type
        }
    )


app = web.Application()

app.on_startup.append(startup)
app.on_cleanup.append(cleanup)

app.router.add_get(
    "/test-health",
    test_health
)

app.router.add_get(
    "/test-status",
    test_status
)

app.router.add_route(
    "*",
    "/{tail:.*}",
    proxy
)

web.run_app(
    app,
    host="0.0.0.0",
    port=19090
)
