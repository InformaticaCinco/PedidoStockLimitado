from dataclasses import replace
from pathlib import Path
import json
import os
import socket
import subprocess
import time
from uuid import uuid4
from urllib.request import Request, urlopen
from urllib.error import URLError

import pytest
from pymongo import MongoClient

from common import Settings, connect, database
from init.replica_set import initialize
from seed.seed import apply_seed
from seed.seed_data import PASSWORD

ROOT = Path(__file__).resolve().parents[1]


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def evidence(name, value):
    (ROOT / '.build' / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def stop(process):
    process.terminate()
    try:
        process.wait(15)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


@pytest.fixture(scope='session')
def mongo_settings():
    binary = Path(os.environ.get('MONGODB_TEST_BINARY', ROOT / '../services/pedidos-java/.build/mongo/mongodb-macos-aarch64-7.0.16/bin/mongod')).resolve()
    assert binary.is_file(), 'Configurar MONGODB_TEST_BINARY con MongoDB 7.0.x real'
    port = free_port()
    folder = ROOT / '.build' / ('mongo-' + uuid4().hex)
    folder.mkdir(parents=True)
    settings = Settings(uri=f'mongodb://localhost:{port}/?replicaSet=rsMongoSeed', replica_set='rsMongoSeed',
                        bootstrap_uri=f'mongodb://127.0.0.1:{port}/?directConnection=true', member_host=f'localhost:{port}')
    with (folder / 'mongod.log').open('w') as log:
        process = subprocess.Popen([str(binary), '--replSet', settings.replica_set, '--bind_ip', '127.0.0.1',
                                    '--port', str(port), '--dbpath', str(folder), '--quiet'], stdout=log, stderr=log)
        try:
            result = initialize(settings)
            evidence('replica.json', result)
            yield settings
        finally:
            stop(process)
            evidence('mongo-process.json', {'pid': process.pid, 'stopped': process.poll() is not None})


@pytest.fixture
def empty_db(mongo_settings):
    settings = replace(mongo_settings, database='mongo_seed_it_' + uuid4().hex)
    with connect(settings) as client:
        db = database(client, settings.database)
        try:
            yield db
        finally:
            # Only this fixture's UUID database; operational seed/reset never drops databases.
            client.drop_database(settings.database)


@pytest.fixture
def db(empty_db):
    apply_seed(empty_db)
    return empty_db


def command(settings, db_name, *arguments):
    env = os.environ | dict(MONGODB_URI=settings.uri, MONGODB_DATABASE=db_name,
                            MONGODB_REPLICA_SET=settings.replica_set, MONGODB_BOOTSTRAP_URI=settings.bootstrap_uri,
                            MONGODB_MEMBER_HOST=settings.member_host, SEED_MODE='upsert', PYTHONDONTWRITEBYTECODE='1')
    return subprocess.run([str(ROOT / '.venv/bin/python'), *arguments], cwd=ROOT, env=env, capture_output=True, text=True)


def http(base, path, body=None, token=None):
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    request = Request(base + path, data=json.dumps(body).encode() if body is not None else None, headers=headers)
    with urlopen(request, timeout=5) as response:
        return response.status, json.load(response)


@pytest.fixture(scope='session')
def java(mongo_settings):
    settings = replace(mongo_settings, database='mongo_seed_java_' + uuid4().hex)
    java_binary = Path(os.environ.get('JAVA_TEST_BINARY', '/Library/Java/JavaVirtualMachines/temurin-21.jdk/Contents/Home/bin/java'))
    jar = (ROOT / '../services/pedidos-java/target/pedidos-1.0.0.jar').resolve()
    keys = (ROOT / '../services/pedidos-java/keys').resolve()
    assert java_binary.is_file() and jar.is_file(), 'Se requiere JAR existente y Java 21; no se recompila'
    port = free_port()
    with connect(settings) as client, (ROOT / '.build' / 'java.log').open('w') as log:
        db = database(client, settings.database)
        apply_seed(db)
        env = os.environ | dict(PORT=str(port), MONGODB_URI=settings.uri, MONGODB_DATABASE=settings.database,
            JWT_PRIVATE_KEY_PATH=str(keys / 'reto-private.pem'), JWT_PUBLIC_KEY_PATH=str(keys / 'reto-public.pem'),
            JWT_ISSUER='http://localhost:8090', JWT_AUDIENCE='pedido-stock-limitado')
        process = subprocess.Popen([str(java_binary), '-jar', str(jar)], cwd=ROOT, env=env, stdout=log, stderr=log)
        base = f'http://127.0.0.1:{port}'
        try:
            for _ in range(100):
                assert process.poll() is None, 'Java terminó: revisar mongo/.build/java.log'
                try:
                    if http(base, '/health')[0] == 200:
                        break
                except URLError:
                    pass
                time.sleep(.1)
            else:
                pytest.fail('Java no arrancó')
            yield base, db
        finally:
            stop(process)
            client.drop_database(settings.database)
            evidence('java-process.json', {'pid': process.pid, 'stopped': process.poll() is not None})
