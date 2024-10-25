#!/usr/bin/env bash

docker compose run --rm mgwatch-backend "conda run --no-capture-output -n mgw ./manage.py $*"
