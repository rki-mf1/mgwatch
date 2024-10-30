#!/usr/bin/env bash

./scripts/dc-dev.sh run --rm mgwatch-backend "conda run --no-capture-output -n mgw ./manage.py $*"
