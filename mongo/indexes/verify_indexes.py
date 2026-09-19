import argparse
from pymongo.errors import OperationFailure

from common import Settings, ToolError, cli, connect, database, require_replica
from indexes.specs import INDEXES


def options(info):
    # Ignore server version/build metadata, but compare every semantic option.
    return dict(unique=bool(info.get('unique', False)), sparse=bool(info.get('sparse', False)),
                hidden=bool(info.get('hidden', False)), expireAfterSeconds=info.get('expireAfterSeconds'),
                partialFilterExpression=info.get('partialFilterExpression'),
                collation=info.get('collation') if info.get('collation', {}).get('locale') != 'simple' else None)


def inspect(db):
    """Read-only preflight of the whole inventory before any index is created."""
    missing, present = [], []
    inventory = {}
    for wanted in INDEXES:
        if wanted.collection not in inventory:
            inventory[wanted.collection] = db[wanted.collection].index_information()
        found = inventory[wanted.collection]
        equivalents = []
        for name, actual in found.items():
            same_fields = tuple(actual['key']) == wanted.keys
            if name == wanted.name or same_fields:
                if not same_fields or options(actual) != options(wanted.options):
                    raise ToolError(f'Índice incompatible: {wanted.collection}.{name}; no se elimina ni reemplaza')
                equivalents.append(name)
        if equivalents:
            present.append({'collection': wanted.collection, 'expectedName': wanted.name, 'actualName': equivalents[0]})
        else:
            missing.append(wanted)
    return missing, present


def converge(db, create=True):
    missing, present = inspect(db)
    if missing and not create:
        raise ToolError('Índices faltantes: ' + ', '.join(f'{i.collection}.{i.name}' for i in missing))
    created = []
    for index in missing:
        try:
            db[index.collection].create_index(list(index.keys), **index.options)
        except OperationFailure as exc:
            raise ToolError(f'No se pudo crear {index.collection}.{index.name}; Mongo code={exc.code}; revisar duplicados/opciones') from exc
        created.append({'collection': index.collection, 'name': index.name})
    return {'ok': True, 'expected': len(INDEXES), 'created': created, 'equivalent': present}


def main():
    parser = argparse.ArgumentParser(description='Convergencia de índices sin borrar definiciones existentes')
    parser.add_argument('--check-only', action='store_true')
    args = parser.parse_args()
    settings = Settings.from_env()
    with connect(settings) as client:
        require_replica(client, settings)
        return converge(database(client, settings.database), create=not args.check_only)


if __name__ == '__main__':
    cli(main)
