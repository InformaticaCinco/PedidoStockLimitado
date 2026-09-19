"""Smoke real independiente de Mongo/JWKS; deja evidencia y detiene su propio proceso."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

import httpx

ROOT = Path(__file__).resolve().parents[1]


def main():
    with socket.socket() as guard:
        guard.bind(('127.0.0.1', 8092))  # Fail if occupied; never probe an unrelated server.
    env = os.environ | dict(PORT='8092', MONGODB_URI='mongodb://127.0.0.1:1/?directConnection=true',
                            MONGODB_DATABASE='cargas_smoke', JWT_JWKS_URL='http://127.0.0.1:1/jwks')
    with (ROOT / '.build' / 'smoke-server.log').open('w') as log:
        process = subprocess.Popen([sys.executable, '-m', 'app.main'], cwd=ROOT, env=env, stdout=log, stderr=log)
        try:
            with httpx.Client(timeout=2, trust_env=False) as client:
                for _ in range(80):
                    assert process.poll() is None, 'El servicio terminó antes del smoke'
                    try:
                        response = client.get('http://127.0.0.1:8092/health', headers={'X-Correlation-Id': 'smoke-cargas-8092'})
                        break
                    except httpx.RequestError:
                        time.sleep(.1)
                else:
                    raise AssertionError('No arrancó en 8092')
                assert response.status_code == 200
                assert response.json()['data'] == {'estado': 'UP'}
                assert response.headers['X-Correlation-Id'] == 'smoke-cargas-8092'
                evidence = dict(port=8092, status=response.status_code, body=response.json(),
                                correlation=response.headers['X-Correlation-Id'], pid=process.pid)
        finally:
            process.terminate()
            try:
                process.wait(15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        evidence['processStopped'] = process.poll() is not None
        (ROOT / '.build' / 'smoke-result.json').write_text(json.dumps(evidence, indent=2) + '\n')
        print(json.dumps(evidence))


if __name__ == '__main__':
    main()
