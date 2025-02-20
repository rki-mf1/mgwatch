#!/usr/bin/env bash

set -xe

# 1. Given a set of SRA identifiers, download signatures from wort
SRA_IDS=$(grep -v '^#' test-data/test-data-sra.ids | tr '\n' ' ')
./scripts/dev-manage.sh create_downloads --ids $SRA_IDS
# 2. Run create_index to create the branchwater index
./scripts/dev-manage.sh create_index
# 3. Run create_metadata with --indexed-only to generate a tiny mongodb with metadata for the indexed sequences
./scripts/dev-manage.sh create_metadata --indexed-only
