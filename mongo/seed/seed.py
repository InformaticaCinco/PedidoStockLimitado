import argparse
from dataclasses import replace
from datetime import datetime, timezone

from pymongo import ReadPreference
from pymongo.errors import CollectionInvalid
from pymongo.read_concern import ReadConcern
from pymongo.write_concern import WriteConcern

from common import Settings, ToolError, cli, connect, database, require_replica
from indexes.verify_indexes import converge
from seed.seed_data import fixture, OPERATIONS


def ensure_collections(db):
    for name in (*fixture(), *OPERATIONS):
        try:
            db.create_collection(name)
        except CollectionInvalid:
            pass


def apply_seed(db, *, reset=False):
    """Default is insert-only. Reset deletes only known operations and identifiable seed masters."""
    ensure_collections(db)
    indexes = converge(db)  # Fail incompatible definitions before deleting any data.
    desired = fixture()
    timestamp = datetime.now(timezone.utc)
    creation = dict(UsuarioCreacion='seed', FechaCreacion=timestamp, UsuarioModificacion=None, FechaModificacion=None)

    def work(session):
        inserted, retained = {}, {}
        # An ID collision with an unrelated master must never be silently adopted or deleted.
        for collection, documents in desired.items():
            for document in documents:
                previous = db[collection].find_one({'_id': document['_id']}, session=session)
                if previous and previous.get('UsuarioCreacion') != 'seed':
                    raise ToolError(f'ID ocupado por maestro ajeno: {collection}/{document["_id"]}')
        if reset:
            for name in OPERATIONS:
                db[name].delete_many({}, session=session)
            for collection, documents in desired.items():
                db[collection].delete_many({'_id': {'$in': [d['_id'] for d in documents]},
                                            'UsuarioCreacion': 'seed'}, session=session)
        for collection, documents in desired.items():
            inserted[collection] = retained[collection] = 0
            for document in documents:
                result = db[collection].update_one({'_id': document['_id']},
                    {'$setOnInsert': document | creation}, upsert=True, session=session)
                if result.upserted_id is not None:
                    inserted[collection] += 1
                else:
                    retained[collection] += 1
        return {'inserted': inserted, 'retained': retained}

    with db.client.start_session() as session:
        changes = session.with_transaction(work, read_concern=ReadConcern('snapshot'),
                                            write_concern=WriteConcern('majority'), read_preference=ReadPreference.PRIMARY)
    return {'ok': True, 'mode': 'reset' if reset else 'upsert', **changes,
            'counts': {name: db[name].count_documents({}) for name in (*desired, *OPERATIONS)},
            'indexesCreated': len(indexes['created'])}


def main():
    parser = argparse.ArgumentParser(description='Seed demo; --reset elimina operaciones conocidas y restaura maestros seed')
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--reset', action='store_true')
    modes.add_argument('--upsert', action='store_true', help='Forzar modo no destructivo, incluso si SEED_MODE=reset')
    args = parser.parse_args()
    settings = Settings.from_env()
    reset = False if args.upsert else args.reset or settings.mode == 'reset'
    with connect(settings) as client:
        server = require_replica(client, settings)
        return apply_seed(database(client, settings.database), reset=reset) | {'server': server}


if __name__ == '__main__':
    cli(main)
