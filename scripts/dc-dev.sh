#!/usr/bin/env bash

docker compose -f compose.yml -f compose-dev.yml "$@"
