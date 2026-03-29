./scripts/build-docker.sh
./scripts/dc-dev.sh up -d --force-recreate --remove-orphans
./scripts/dev-manage.sh test
