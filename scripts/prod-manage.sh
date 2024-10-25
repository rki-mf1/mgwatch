#!/usr/bin/env bash

./scripts/prod-dev.sh run --rm mgwatch-backend "conda run --no-capture-output -n mgw ./manage.py $*"
