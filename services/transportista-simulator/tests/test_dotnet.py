"""Runs unmodified .NET client source against a real aiohttp listener."""
import asyncio
import json
import os
from decimal import Decimal
from pathlib import Path

import pytest

from app.main import Config

ROOT = Path(__file__).resolve().parents[1]
DLL = ROOT / "tests/dotnet-client/bin/Debug/net10.0/Compatibilidad.dll"


@pytest.mark.parametrize("mode", ["normal", "partial"])
async def test_cliente_dotnet_real(servidor, mode):
    if os.environ.get("RUN_DOTNET_COMPAT") != "1":
        pytest.skip("Configurar RUN_DOTNET_COMPAT=1 y compilar tests/dotnet-client")
    assert DLL.exists(), "Compilar Compatibilidad.csproj antes de ejecutar"
    env = os.environ | {"DOTNET_CLI_HOME": str(ROOT / ".build/dotnet"), "DOTNET_CLI_TELEMETRY_OPTOUT": "1", "DOTNET_GENERATE_ASPNET_CERTIFICATE": "false"}
    async with servidor(Config(failure_rate=0, partial_rate=1 if mode == "partial" else 0, latency_ms=10)) as s:
        process = await asyncio.create_subprocess_exec("dotnet", str(DLL), s.url, mode,
            cwd=ROOT, env=env, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=30)
        finally:
            if process.returncode is None:
                process.kill()
                await process.wait()
        assert process.returncode == 0, stderr.decode()
        result = json.loads(stdout)
        assert result["numeroGuia"] == "G-000001"
        assert result["error"] == ("TRANSPORTISTA_CONEXION" if mode == "partial" else None)
        assert s.state.correlativo == 1
        guide = s.state.por_clave["despacho-guia-PED-DOTNET"]
        assert guide.solicitud.pedido_id == "PED-DOTNET"
        assert guide.solicitud.peso_kg == Decimal("12.4")
        assert guide.solicitud.zona == "LIMA_METROPOLITANA"
        assert guide.estado == "ANULADA"
        print("DOTNET:", json.dumps(result))
