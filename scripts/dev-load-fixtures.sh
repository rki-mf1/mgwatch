#!/usr/bin/env bash

set -e

scripts/dev-manage.sh loaddata dev/users
scripts/dev-manage.sh loaddata dev/data
