#!/usr/bin/env bash

./scripts/dc-prod.sh run --rm mgwatch "pixi run --frozen ./manage.py $*"
