"""Inicialización idempotente, sin reconfiguración ni borrado de datos."""
import time

from pymongo import MongoClient
from pymongo.errors import ConnectionFailure, OperationFailure

from common import Settings, ToolError, cli


def bootstrap(settings):
    return MongoClient(settings.bootstrap_uri, directConnection=True, serverSelectionTimeoutMS=1000,
                       connectTimeoutMS=1000, socketTimeoutMS=3000)


def wait_connected(client, timeout):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        try:
            version = client.server_info()['version']
            if not version.startswith('7.0.'):
                raise ToolError('Se requiere MongoDB 7.0.x')
            return version
        except ConnectionFailure:
            time.sleep(.2)
    raise ToolError('Timeout esperando mongod')


def wait_primary(client, settings):
    end = time.monotonic() + settings.timeout
    while time.monotonic() < end:
        try:
            hello = client.admin.command('hello')
            if hello.get('isWritablePrimary'):
                if hello.get('setName') != settings.replica_set or hello.get('hosts') != [settings.member_host]:
                    raise ToolError('PRIMARY tiene configuración diferente; no se reconfigura automáticamente')
                return {'primary': True, 'replicaSet': settings.replica_set, 'member': settings.member_host}
        except ConnectionFailure:
            pass
        time.sleep(.2)
    raise ToolError('Timeout esperando PRIMARY')


def initialize(settings):
    with bootstrap(settings) as client:
        version = wait_connected(client, settings.timeout)
        desired = {'_id': settings.replica_set, 'members': [{'_id': 0, 'host': settings.member_host}]}
        created = False
        try:
            config = client.admin.command('replSetGetConfig')['config']
        except OperationFailure as exc:
            if exc.code != 94:  # NotYetInitialized; other failures must not be swallowed.
                raise
            try:
                client.admin.command('replSetInitiate', desired)
                created = True
            except OperationFailure as race:
                if race.code != 23:  # Another init job won: AlreadyInitialized.
                    raise
            config = client.admin.command('replSetGetConfig')['config']
        members = config.get('members', [])
        if config['_id'] != settings.replica_set or len(members) != 1 or members[0]['host'] != settings.member_host:
            raise ToolError('Replica set ya configurado de otra forma; no se ejecuta rs.reconfig')
        return {'ok': True, 'initialized': created, 'version': version, **wait_primary(client, settings)}


if __name__ == '__main__':
    cli(lambda: initialize(Settings.from_env()))
