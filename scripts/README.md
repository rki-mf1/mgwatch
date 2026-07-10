Run these scripts from the project root directory, not from this directory.

e.g.

```
$ cd ~/src/mgwatch
$ ./scripts/build-docker.sh
$ ./scripts/dev-manage.sh create_metadata
```

Standalone remote index builder:

```
$ python scripts/wort-standalone-index-builder.py --accessions-file accessions.txt --output-dir /tmp/wort-build
```

This script downloads only one index batch of Wort signatures at a time, builds the
corresponding rocksdb indexes, records progress in `builder-state.json`, and deletes
indexed signatures by default to keep disk usage bounded while still allowing safe
stop-and-resume runs.

Prepare/apply builder state bundles:

```bash
$ python scripts/wort-state-bundle.py prepare --bundle-dir /tmp/wort-state
$ python scripts/wort-state-bundle.py apply --builder-output-dir /tmp/wort-build
```

`prepare` exports the current `work/data/backend-data/SRA/metagenomes` state into a
portable bundle for remote standalone runs. `apply` merges a completed standalone
builder output directory back into the local `work/` tree.

Testing:

```
$ python -m unittest mgw_api.tests.test_wort_index_builder
$ python -m unittest mgw_api.tests.test_wort_state_bundle
```
