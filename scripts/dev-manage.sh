#!/usr/bin/env bash

./scripts/dc-dev.sh run --rm mgwatch "conda run --no-capture-output -n mgw ./manage.py $*"
