#!/usr/bin/env bash

./scripts/dc-dev.sh run --rm mgwatch "pixi run --frozen ./manage.py $*"
