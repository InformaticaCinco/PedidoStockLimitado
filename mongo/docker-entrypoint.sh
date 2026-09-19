#!/bin/sh
set -eu
# The existing initializer waits for connectivity before initiating the replica set.
python -m init.replica_set
python -m init.wait_for_primary
python -m seed.seed --upsert
python -m indexes.verify_indexes --check-only
python -m seed.validate
