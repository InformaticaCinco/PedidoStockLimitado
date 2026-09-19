from common import Settings, cli
from init.replica_set import bootstrap, wait_connected, wait_primary


def main():
    settings = Settings.from_env()
    with bootstrap(settings) as client:
        version = wait_connected(client, settings.timeout)
        return {'ok': True, 'version': version, **wait_primary(client, settings)}


if __name__ == '__main__':
    cli(main)
