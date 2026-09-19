"""Configuración y acceso compartidos por las herramientas de mongo/."""
from dataclasses import dataclass
import json
import os
import re
import sys

from pymongo import MongoClient, ReadPreference
from pymongo.errors import PyMongoError
from pymongo.read_concern import ReadConcern
from pymongo.write_concern import WriteConcern


class ToolError(Exception):
    pass


@dataclass(frozen=True)
class Settings:
    uri: str = 'mongodb://127.0.0.1:27017/?replicaSet=rs0'
    database: str = 'pedidos_stock'
    replica_set: str = 'rs0'
    bootstrap_uri: str = 'mongodb://127.0.0.1:27017/?directConnection=true'
    member_host: str = 'localhost:27017'
    timeout: int = 30
    mode: str = 'upsert'

    def __post_init__(self):
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,63}', self.database) or self.database in {'admin', 'config', 'local'}:
            raise ToolError('MONGODB_DATABASE debe ser una base funcional válida, nunca admin/config/local')
        if self.mode not in {'upsert', 'reset'}:
            raise ToolError('SEED_MODE debe ser upsert o reset')
        if not 1 <= self.timeout <= 300:
            raise ToolError('MONGODB_TIMEOUT_SECONDS debe estar entre 1 y 300')
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', self.replica_set):
            raise ToolError('MONGODB_REPLICA_SET inválido')
        if not re.fullmatch(r'[A-Za-z0-9.-]+:[0-9]{1,5}', self.member_host) or not 1 <= int(self.member_host.rsplit(':', 1)[1]) <= 65535:
            raise ToolError('MONGODB_MEMBER_HOST debe ser hostname:puerto')

    @classmethod
    def from_env(cls):
        defaults = cls()
        return cls(uri=os.getenv('MONGODB_URI', defaults.uri), database=os.getenv('MONGODB_DATABASE', defaults.database),
                   replica_set=os.getenv('MONGODB_REPLICA_SET', defaults.replica_set),
                   bootstrap_uri=os.getenv('MONGODB_BOOTSTRAP_URI', defaults.bootstrap_uri),
                   member_host=os.getenv('MONGODB_MEMBER_HOST', defaults.member_host),
                   timeout=int(os.getenv('MONGODB_TIMEOUT_SECONDS', defaults.timeout)),
                   mode=os.getenv('SEED_MODE', defaults.mode))


def connect(settings):
    client = MongoClient(settings.uri, serverSelectionTimeoutMS=settings.timeout * 1000,
                         connectTimeoutMS=3000, socketTimeoutMS=10000, tz_aware=True)
    return client


def database(client, name):
    return client.get_database(name, read_concern=ReadConcern('majority'),
                              write_concern=WriteConcern('majority'), read_preference=ReadPreference.PRIMARY)


def require_replica(client, settings):
    version = client.server_info()['version']
    hello = client.admin.command('hello')
    if not version.startswith('7.0.'):
        raise ToolError('Se requiere MongoDB 7.0.x')
    if hello.get('setName') != settings.replica_set or not hello.get('isWritablePrimary') or len(hello.get('hosts', [])) != 1:
        raise ToolError('Se requiere PRIMARY del replica set configurado de un nodo')
    return {'version': version, 'replicaSet': hello['setName'], 'primary': True}


def cli(main):
    try:
        result = main()
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except ToolError as exc:
        print(json.dumps({'ok': False, 'error': str(exc)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(2)
    except (PyMongoError, ValueError) as exc:
        # Avoid including connection strings/credentials in generic driver errors.
        print(json.dumps({'ok': False, 'error': type(exc).__name__, 'code': getattr(exc, 'code', None)}), file=sys.stderr)
        raise SystemExit(2)
