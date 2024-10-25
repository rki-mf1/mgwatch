#!/usr/bin/env bash

set -e

# Disable creating migrations and migrating, by default
# Note: in bash 0 = true, 1 = false
BUILD_CONTAINER=1
CREATE_MIGRATIONS=1
MIGRATE=1

while getopts "bcmh" opt; do
  case $opt in
    b) BUILD_CONTAINER=0 ;;
    c) CREATE_MIGRATIONS=0 ;;
    m) MIGRATE=0 ;;
    h)
      echo "./mgw.sh [-c] [-m]"
      echo " -b     build backend docker container"
      echo " -c     create (=make) migrations"
      echo " -m     migrate"
      exit 0
      ;;
  esac
done

./scripts/dc-dev.sh down --remove-orphans
[[ BUILD_CONTAINER ]] && ./scripts/build-docker.sh
./scripts/dc-dev.sh up -d
[[ CREATE_MIGRATIONS ]] && ./scripts/backend-manage.sh makemigrations
[[ MIGRATE ]] && ./scripts/backend-manage.sh migrate
