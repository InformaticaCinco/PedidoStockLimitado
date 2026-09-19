"""Servidor pequeño: idempotencia, fallos y corte real después de crear una guía."""
from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import random
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Callable, Mapping

from aiohttp import web

LOG = logging.getLogger("transportista-simulator")
ZONAS = {"LIMA_METROPOLITANA", "LIMA_PROVINCIA", "PROVINCIA"}


@dataclass(frozen=True)
class Config:
    port: int = 9090
    failure_rate: float = 0.3
    partial_rate: float = 0.1
    latency_ms: int = 3000

    def __post_init__(self) -> None:
        if type(self.port) is not int or not 1 <= self.port <= 65535:
            raise ValueError("PORT debe ser un entero entre 1 y 65535")
        for name in ("failure_rate", "partial_rate"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
                raise ValueError(f"{name.upper()} debe estar entre 0.0 y 1.0")
        if type(self.latency_ms) is not int or self.latency_ms <= 0:
            raise ValueError("LATENCY_MS debe ser un entero positivo")

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Config:
        env = os.environ if env is None else env
        try:
            return cls(int(env.get("PORT", "9090")), float(env.get("FAILURE_RATE", "0.3")),
                       float(env.get("PARTIAL_RATE", "0.1")), int(env.get("LATENCY_MS", "3000")))
        except (ValueError, OverflowError) as exc:
            # Do not echo arbitrary environment contents in diagnostics.
            raise ValueError("Configuración inválida: PORT, FAILURE_RATE, PARTIAL_RATE o LATENCY_MS") from exc

    @property
    def failure_delay_seconds(self) -> float:
        # Strictly above LATENCY_MS; default 6001 ms also exceeds .NET's default 5 s.
        return (2 * self.latency_ms + 1) / 1000


@dataclass(frozen=True)
class Solicitud:
    pedido_id: str
    peso_kg: Decimal
    zona: str


@dataclass
class Guia:
    numero: str
    solicitud: Solicitud
    idempotency_key: str
    estado: str = "ACTIVA"
    creada: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    anulada: datetime | None = None


class Estado:
    def __init__(self, config: Config, azar: Callable[[], float] | None = None):
        self.config = config
        self.azar = azar if azar is not None else random.random
        self.lock = asyncio.Lock()
        self.por_clave: dict[str, Guia] = {}
        self.por_numero: dict[str, Guia] = {}
        self.por_pedido: dict[str, list[Guia]] = {}
        self.correlativo = 0
        self.fallos = 0

    def crear(self, key: str, solicitud: Solicitud) -> Guia:
        """Caller holds lock; no await between numbering and all index writes."""
        self.correlativo += 1
        guia = Guia(f"G-{self.correlativo:06d}", solicitud, key)
        self.por_clave[key] = guia
        self.por_numero[guia.numero] = guia
        self.por_pedido.setdefault(solicitud.pedido_id, []).append(guia)
        return guia


STATE = web.AppKey("estado", Estado)
CORRELATION = web.RequestKey("correlationId", str)
PEDIDO = web.RequestKey("pedidoId", str)


def evento(request: web.Request, resultado: str, guia: Guia | None = None) -> None:
    # Route template (not query/body) prevents accidental logging of arbitrary inputs.
    route = request.match_info.route.resource
    ruta = route.canonical if route is not None else "NO_ROUTE"
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(), "level": "INFO",
        "servicio": "transportista-simulator", "correlationId": request[CORRELATION],
        "metodo": request.method, "ruta": ruta, "resultado": resultado,
    }
    if PEDIDO in request:
        entry["pedidoId"] = request[PEDIDO]
    if guia is not None:
        entry["pedidoId"] = guia.solicitud.pedido_id
        entry["numeroGuia"] = guia.numero
    LOG.info(json.dumps(entry, ensure_ascii=False))


@web.middleware
async def contexto(request: web.Request, handler):
    request[CORRELATION] = request.headers.get("X-Correlation-Id") or str(uuid.uuid4())
    try:
        response = await handler(request)
    except web.HTTPException as exc:
        evento(request, f"HTTP_{exc.status}")
        response = web.json_response({"error": "Solicitud rechazada"}, status=exc.status)
    except Exception:
        evento(request, "INTERNAL_ERROR")
        response = web.json_response({"error": "Error interno"}, status=500)
    response.headers["X-Correlation-Id"] = request[CORRELATION]
    return response


def sin_duplicados(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Campo JSON repetido")
        result[key] = value
    return result


def constante_invalida(value):
    raise ValueError("Constante JSON no finita")


async def entrada(request: web.Request) -> tuple[str, Solicitud]:
    key = request.headers.get("Idempotency-Key")
    if key is None or not key.strip():
        raise web.HTTPBadRequest()
    try:
        body = json.loads(await request.text(), parse_float=Decimal, parse_int=Decimal,
                          parse_constant=constante_invalida, object_pairs_hook=sin_duplicados)
        if not isinstance(body, dict) or set(body) != {"pedidoId", "pesoKg", "zona"}:
            raise ValueError()
        pedido, peso, zona = body["pedidoId"], body["pesoKg"], body["zona"]
        if not isinstance(pedido, str) or not pedido.strip():
            raise ValueError()
        if not isinstance(peso, Decimal) or not peso.is_finite() or peso <= 0:
            raise ValueError()
        if not isinstance(zona, str) or zona not in ZONAS:
            raise ValueError()
        return key, Solicitud(pedido, peso, zona)
    except (ValueError, TypeError, InvalidOperation, UnicodeError, RecursionError):
        raise web.HTTPBadRequest() from None


async def health(request: web.Request) -> web.Response:
    evento(request, "HEALTH_UP")
    return web.json_response({"estado": "UP"})


async def generar(request: web.Request) -> web.Response:
    key, solicitud = await entrada(request)
    request[PEDIDO] = solicitud.pedido_id
    state = request.app[STATE]
    # Serialization covers lookup, both random decisions and index/sequence writes.
    # Slow fault simulation stays outside this lock, so GET/replay/health never wait for it.
    async with state.lock:
        if guia := state.por_clave.get(key):
            if guia.solicitud != solicitud:
                evento(request, "IDEMPOTENCY_CONFLICT", guia)
                return web.json_response({"error": "Idempotency-Key utilizada con otro contenido"}, status=409)
            evento(request, "IDEMPOTENT_REPLAY", guia)
            return web.json_response({"numeroGuia": guia.numero})
        if state.azar() < state.config.partial_rate:
            guia = state.crear(key, solicitud)
            evento(request, "PARTIAL_CONNECTION_CLOSED", guia)
            # No prepare()/write(): zero HTTP response bytes before aborting the transport.
            if request.transport is not None:
                request.transport.abort()
            # aiohttp requires a Response return; transport is already closed so none is sent.
            return web.Response()
        if state.azar() < state.config.failure_rate:
            fault = state.fallos % 3
            state.fallos += 1
        else:
            guia = state.crear(key, solicitud)
            evento(request, "CREATED", guia)
            return web.json_response({"numeroGuia": guia.numero}, status=201)
    if fault < 2:
        status = 500 if fault == 0 else 503
        evento(request, f"FAILURE_{status}")
        return web.json_response({"error": "Fallo simulado"}, status=status)
    evento(request, "FAILURE_TIMEOUT")
    await asyncio.sleep(state.config.failure_delay_seconds)
    return web.json_response({"error": "Demora simulada sin crear guía"}, status=503)


async def consultar(request: web.Request) -> web.Response:
    pedido = request.query.get("pedidoId")
    if pedido is None or not pedido.strip():
        raise web.HTTPBadRequest()
    request[PEDIDO] = pedido
    state = request.app[STATE]
    async with state.lock:
        guias = state.por_pedido.get(pedido, [])
        activa = next((g for g in guias if g.estado == "ACTIVA"), None)
        listado = [{"numeroGuia": g.numero, "estado": g.estado} for g in guias]
        if activa is None:
            evento(request, "NOT_FOUND")
            return web.json_response({"error": "No existe guía activa", "guias": listado}, status=404)
        evento(request, "FOUND", activa)
        return web.json_response({"numeroGuia": activa.numero, "guias": listado})


async def anular(request: web.Request) -> web.Response:
    state = request.app[STATE]
    async with state.lock:
        guia = state.por_numero.get(request.match_info["numero"])
        if guia is None:
            evento(request, "NOT_FOUND")
            return web.json_response({"error": "Guía no encontrada"}, status=404)
        if guia.estado == "ANULADA":
            evento(request, "ALREADY_CANCELLED", guia)
        else:
            guia.estado = "ANULADA"
            guia.anulada = datetime.now(timezone.utc)
            evento(request, "CANCELLED", guia)
        return web.json_response({"numeroGuia": guia.numero, "estado": guia.estado})


def create_app(config: Config | None = None, *, azar: Callable[[], float] | None = None) -> web.Application:
    app = web.Application(middlewares=[contexto], client_max_size=64 * 1024)
    app[STATE] = Estado(config if config is not None else Config.from_env(), azar)
    app.add_routes([web.get("/health", health), web.post("/guias", generar),
                    web.get("/guias", consultar), web.post("/guias/{numero}/anulacion", anular)])
    return app


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)
    logging.getLogger("aiohttp.access").disabled = True
    logging.getLogger("aiohttp.server").disabled = True
    try:
        config = Config.from_env()
    except ValueError as exc:
        print(json.dumps({"level": "ERROR", "servicio": "transportista-simulator", "resultado": "CONFIG_INVALID", "error": str(exc)}), file=sys.stderr)
        raise SystemExit(2) from None
    web.run_app(create_app(config), host="0.0.0.0", port=config.port, print=None, access_log=None)


if __name__ == "__main__":
    main()
