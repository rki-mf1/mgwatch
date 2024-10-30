#!/usr/bin/env bash

./scripts/dc-prod.sh run --rm mgwatch-backend "conda run --no-capture-output -n mgw ./manage.py $*"
