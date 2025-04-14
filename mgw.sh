#!/usr/bin/env bash

set -e

# Disable creating migrations and migrating, by default
# Note: in bash 0 = true, 1 = false
BUILD_CONTAINER=1
CREATE_MIGRATIONS=1
MIGRATE=1
SHOW_LOGS=1
LOAD_DATA=1

while getopts "bcmldh" opt; do
  case $opt in
    b) BUILD_CONTAINER=0 ;;
    c) CREATE_MIGRATIONS=0 ;;
    m) MIGRATE=0 ;;
    l) SHOW_LOGS=0 ;;
    d) LOAD_DATA=0 ;;
    h)
      echo "./mgw.sh [-b] [-c] [-m]"
      echo " -b     build backend docker container"
      echo " -c     create (=make) migrations"
      echo " -m     migrate"
      echo " -d     load test data and user accounts for development"
      echo " -l     follow logs when everything has started"
      exit 0
      ;;
  esac
done

./scripts/dc-dev.sh down --remove-orphans
[[ BUILD_CONTAINER -eq 0 ]] && ./scripts/build-docker.sh
./scripts/dc-dev.sh up -d --force-recreate
./scripts/dev-manage.sh collectstatic --no-input
[[ CREATE_MIGRATIONS -eq 0 ]] && ./scripts/dev-manage.sh makemigrations
[[ MIGRATE -eq 0 ]] && ./scripts/dev-manage.sh migrate
[[ LOAD_DATA -eq 0 ]] && ./scripts/dev-load-fixtures.sh
[[ SHOW_LOGS -eq 0 ]] && ./scripts/dc-dev.sh logs -tf
