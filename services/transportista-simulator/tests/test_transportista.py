import asyncio
import json
import logging
import time
from decimal import Decimal

import aiohttp
import pytest

from app.main import Config


async def test_health_real(servidor):
    async with servidor(Config(failure_rate=1, partial_rate=1)) as s:
        response = await s.client.get(s.url + "/health")
        assert response.status == 200
        assert await response.json() == {"estado": "UP"}
        assert s.state.correlativo == 0


async def test_creacion_y_replay_no_duplican(servidor):
    async with servidor() as s:
        first = await s.post()
        assert first.status == 201
        assert await first.json() == {"numeroGuia": "G-000001"}
        replay = await s.post()
        assert replay.status == 200
        assert await replay.json() == await first.json()
        assert s.state.correlativo == len(s.state.por_numero) == 1


async def test_misma_clave_otro_contenido_conflicto(servidor):
    async with servidor() as s:
        await s.post()
        response = await s.post(body={"pedidoId": "OTRO", "pesoKg": 1, "zona": "PROVINCIA"})
        assert response.status == 409
        assert s.state.por_clave["clave-1"].solicitud.pedido_id == "PED-001"
        assert s.state.correlativo == 1


async def test_peso_numericamente_igual_es_replay(servidor):
    async with servidor() as s:
        raw = '{"pedidoId":"sin regex impuesta","pesoKg":12.400,"zona":"PROVINCIA"}'
        first = await s.client.post(s.url + "/guias", data=raw, headers={"Idempotency-Key": "a"})
        second = await s.post("a", {"pedidoId": "sin regex impuesta", "pesoKg": 12.4, "zona": "PROVINCIA"})
        assert first.status == 201 and second.status == 200
        assert s.state.por_clave["a"].solicitud.peso_kg == Decimal("12.4")


async def test_claves_distintas_crean_dos_y_get_elige_primera(servidor):
    async with servidor() as s:
        await s.post("a")
        await s.post("b")
        response = await s.get()
        assert response.status == 200
        assert await response.json() == {"numeroGuia": "G-000001", "guias": [
            {"numeroGuia": "G-000001", "estado": "ACTIVA"},
            {"numeroGuia": "G-000002", "estado": "ACTIVA"}]}


async def test_anular_y_repetir_preserva_historial_y_fecha(servidor):
    async with servidor() as s:
        await s.post()
        first = await s.client.post(s.url + "/guias/G-000001/anulacion")
        assert first.status == 200
        assert await first.json() == {"numeroGuia": "G-000001", "estado": "ANULADA"}
        fecha = s.state.por_numero["G-000001"].anulada
        second = await s.client.post(s.url + "/guias/G-000001/anulacion")
        assert second.status == 200
        assert s.state.por_numero["G-000001"].anulada == fecha
        assert fecha is not None
        lookup = await s.get()
        assert lookup.status == 404
        assert (await lookup.json())["guias"] == [{"numeroGuia": "G-000001", "estado": "ANULADA"}]
        replay = await s.post()
        assert replay.status == 200 and s.state.por_numero["G-000001"].estado == "ANULADA"


async def test_get_con_anulada_y_activa_conserva_todas(servidor):
    async with servidor() as s:
        await s.post("a")
        await s.post("b")
        await s.client.post(s.url + "/guias/G-000001/anulacion")
        response = await s.get()
        data = await response.json()
        assert data["numeroGuia"] == "G-000002"
        assert [g["estado"] for g in data["guias"]] == ["ANULADA", "ACTIVA"]


async def test_ausencia_consulta_y_anulacion(servidor):
    async with servidor() as s:
        assert (await s.get()).status == 404
        assert (await s.client.post(s.url + "/guias/inexistente/anulacion")).status == 404


async def test_failure_ciclo_y_demora_no_consumen_clave(servidor):
    async with servidor(Config(failure_rate=1, partial_rate=0, latency_ms=20)) as s:
        statuses = []
        for _ in range(2):
            for expected in [500, 503, 503]:
                inicio = time.monotonic()
                response = await s.post()
                elapsed = time.monotonic() - inicio
                statuses.append(response.status)
                assert response.status == expected
                if s.state.fallos % 3 == 0:
                    assert elapsed >= s.state.config.failure_delay_seconds
                assert s.state.correlativo == 0
                assert not s.state.por_clave
                assert (await s.get()).status == 404
        assert statuses == [500, 503, 503, 500, 503, 503]
        # After all failures the same key can create; injected randomness is test-only.
        s.state.azar = lambda: 1.0
        response = await s.post()
        assert response.status == 201 and await response.json() == {"numeroGuia": "G-000001"}


async def test_demora_provoca_timeout_real_y_no_bloquea_health(servidor):
    async with servidor(Config(failure_rate=1, partial_rate=0, latency_ms=100)) as s:
        await s.post()
        await s.post()
        with pytest.raises(asyncio.TimeoutError):
            await s.post(timeout=aiohttp.ClientTimeout(total=0.03))
        async with asyncio.timeout(0.1):
            assert (await s.client.get(s.url + "/health")).status == 200
            assert (await s.get()).status == 404
        assert not s.state.por_clave


async def test_partial_corta_tcp_recupera_get_y_replay(servidor, caplog):
    caplog.set_level(logging.INFO, logger="transportista-simulator")
    async with servidor(Config(partial_rate=1, failure_rate=1, latency_ms=10)) as s:
        with pytest.raises(aiohttp.ClientConnectionError) as error:
            await s.post()
        response = await s.get()
        assert response.status == 200
        data = await response.json()
        assert data == {"numeroGuia": "G-000001", "guias": [{"numeroGuia": "G-000001", "estado": "ACTIVA"}]}
        assert (await s.post()).status == 200
        assert s.state.correlativo == 1 and len(s.state.por_clave) == 1
        assert s.state.fallos == 0  # PARTIAL evaluated before FAILURE, even when both are 1.
        print(f"PARTIAL: {type(error.value).__name__}; GET 200 {data}; replay 200; guias=1")
        assert any(json.loads(r.message)["resultado"] == "PARTIAL_CONNECTION_CLOSED" for r in caplog.records)


async def test_concurrencia_misma_clave_crea_una(servidor):
    async with servidor() as s:
        gate = asyncio.Event()
        async def send():
            await gate.wait()
            response = await s.post()
            return response.status, await response.json()
        tasks = [asyncio.create_task(send()) for _ in range(30)]
        gate.set()
        results = await asyncio.gather(*tasks)
        assert sum(status == 201 for status, _ in results) == 1
        assert sum(status == 200 for status, _ in results) == 29
        assert {data["numeroGuia"] for _, data in results} == {"G-000001"}
        assert s.state.correlativo == 1


async def test_concurrencia_claves_distintas_no_deduplica_pedido(servidor):
    async with servidor() as s:
        responses = await asyncio.gather(*(s.post(f"key-{i}") for i in range(30)))
        assert all(r.status == 201 for r in responses)
        numbers = {(await r.json())["numeroGuia"] for r in responses}
        assert len(numbers) == 30
        assert len((await (await s.get()).json())["guias"]) == 30


async def test_correlation_y_log_json_sin_tokens(servidor, caplog):
    caplog.set_level(logging.INFO, logger="transportista-simulator")
    async with servidor() as s:
        response = await s.client.post(s.url + "/guias", json={"pedidoId": "PED-123", "pesoKg": 1, "zona": "PROVINCIA"},
                                       headers={"Idempotency-Key": "key", "X-Correlation-Id": "corr-123", "Authorization": "Bearer secreto-no-registrar"})
        assert response.headers["X-Correlation-Id"] == "corr-123"
        record = json.loads(caplog.records[-1].message)
        assert record["correlationId"] == "corr-123" and record["pedidoId"] == "PED-123"
        assert record["numeroGuia"] == "G-000001" and record["resultado"] == "CREATED"
        assert record["ruta"] == "/guias" and record["metodo"] == "POST"
        assert "secreto-no-registrar" not in caplog.text


async def test_instancia_nueva_empieza_limpia(servidor):
    async with servidor() as first:
        await first.post()
    async with servidor() as second:
        assert (await second.get()).status == 404
        assert await (await second.post()).json() == {"numeroGuia": "G-000001"}


@pytest.mark.parametrize("raw", [
    '{', '[]', '{}',
    '{"pedidoId":"P","pesoKg":true,"zona":"PROVINCIA"}',
    '{"pedidoId":"P","pesoKg":"1","zona":"PROVINCIA"}',
    '{"pedidoId":"P","pesoKg":0,"zona":"PROVINCIA"}',
    '{"pedidoId":"P","pesoKg":-1,"zona":"PROVINCIA"}',
    '{"pedidoId":"P","pesoKg":NaN,"zona":"PROVINCIA"}',
    '{"pedidoId":{},"pesoKg":1,"zona":"PROVINCIA"}',
    '{"pedidoId":" ","pesoKg":1,"zona":"PROVINCIA"}',
    '{"pedidoId":"P","pesoKg":1,"zona":"OTRA"}',
    '{"pedidoId":"P","pesoKg":1,"zona":{}}',
    '{"pedidoId":"P","pesoKg":1,"zona":"PROVINCIA","extra":true}',
    '{"pedidoId":"P","pedidoId":"Q","pesoKg":1,"zona":"PROVINCIA"}',
])
async def test_entrada_invalida_no_consume_clave(servidor, raw):
    async with servidor() as s:
        response = await s.client.post(s.url + "/guias", data=raw, headers={"Idempotency-Key": "key"})
        assert response.status == 400
        assert not s.state.por_clave


@pytest.mark.parametrize("key", [None, "", "   "])
async def test_clave_obligatoria(servidor, key):
    async with servidor() as s:
        response = await s.client.post(s.url + "/guias", json={"pedidoId": "P", "pesoKg": 1, "zona": "PROVINCIA"}, headers={} if key is None else {"Idempotency-Key": key})
        assert response.status == 400


@pytest.mark.parametrize("name,value", [("FAILURE_RATE", "-0.1"), ("FAILURE_RATE", "1.1"), ("FAILURE_RATE", "nan"),
    ("PARTIAL_RATE", "inf"), ("PARTIAL_RATE", "x"), ("LATENCY_MS", "0"), ("LATENCY_MS", "-1"),
    ("LATENCY_MS", "1.5"), ("PORT", "0"), ("PORT", "65536"), ("PORT", "abc")])
def test_config_invalida(name, value):
    with pytest.raises(ValueError, match="Configuración inválida"):
        Config.from_env({name: value})


def test_defaults_exactos():
    assert Config.from_env({}) == Config(9090, 0.3, 0.1, 3000)
    assert Config().failure_delay_seconds == 6.001


async def test_partial_concurrente_una_creacion_y_un_corte(servidor):
    async with servidor(Config(failure_rate=1, partial_rate=1, latency_ms=10)) as s:
        results = await asyncio.gather(*(s.post() for _ in range(20)), return_exceptions=True)
        assert sum(isinstance(r, aiohttp.ClientConnectionError) for r in results) == 1
        successes = [r for r in results if not isinstance(r, Exception)]
        assert len(successes) == 19 and all(r.status == 200 for r in successes)
        assert s.state.correlativo == 1
        assert len((await (await s.get()).json())["guias"]) == 1


async def test_get_requiere_pedido(servidor):
    async with servidor() as s:
        assert (await s.client.get(s.url + "/guias")).status == 400


async def test_arranque_con_config_invalida_sale_sin_servidor():
    import os
    import sys
    process = await asyncio.create_subprocess_exec(sys.executable, "-m", "app.main",
        env=os.environ | {"FAILURE_RATE": "no-valido"},
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    stdout, stderr = await asyncio.wait_for(process.communicate(), 5)
    assert process.returncode == 2
    assert json.loads(stderr)["resultado"] == "CONFIG_INVALID"
    assert not stdout
