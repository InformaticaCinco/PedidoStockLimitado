"""Manual smoke on the required port; always shuts down the spawned process."""
import asyncio
import json
import os
from pathlib import Path
import socket
import sys

from aiohttp import ClientError, ClientSession, ClientTimeout

ROOT = Path(__file__).resolve().parents[1]


async def main():
    # Fail rather than test an unrelated process already bound to 9090.
    with socket.socket() as check:
        check.bind(("127.0.0.1", 9090))
    build = ROOT / ".build"
    build.mkdir(exist_ok=True)
    env = os.environ | {"PORT": "9090", "FAILURE_RATE": "0", "PARTIAL_RATE": "0", "LATENCY_MS": "10"}
    with (build / "smoke-server.log").open("w") as log:
        process = await asyncio.create_subprocess_exec(sys.executable, "-m", "app.main",
            cwd=ROOT, env=env, stdout=log, stderr=log)
        try:
            async with ClientSession(timeout=ClientTimeout(total=1)) as client:
                async with asyncio.timeout(15):
                    while True:
                        if process.returncode is not None:
                            raise RuntimeError("El servidor terminó antes de health")
                        try:
                            async with client.get("http://127.0.0.1:9090/health", headers={"X-Correlation-Id": "smoke-9090"}) as response:
                                data = await response.json()
                                assert response.status == 200 and data == {"estado": "UP"}
                                assert response.headers["X-Correlation-Id"] == "smoke-9090"
                                result = {"port": 9090, "status": response.status, "body": data, "correlationId": response.headers["X-Correlation-Id"]}
                                (build / "smoke-result.json").write_text(json.dumps(result, indent=2) + "\n")
                                print(json.dumps(result))
                                break
                        except (ClientError, TimeoutError):
                            await asyncio.sleep(0.05)
        finally:
            if process.returncode is None:
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), 5)
                except TimeoutError:
                    process.kill()
                    await process.wait()


if __name__ == "__main__":
    asyncio.run(main())
