#!/usr/bin/env bash

################################################################
#mamba
mamba_envs=("mgw")
if command -v mamba &> /dev/null; then
  echo "# Mamba is installed."
else
  echo "# Mamba is not installed."
  echo "# Please download and install Miniforge3:"
  echo '#     curl -L -O "https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-$(uname)-$(uname -m).sh"'
  echo '#     bash Miniforge3-$(uname)-$(uname -m).sh'
  exit 1
fi

for i in "${!mamba_envs[@]}"; do
  if mamba info --envs | grep -q "^${mamba_envs[i]}\s"; then
    echo "# Mamba environment ${mamba_envs[i]} already exists."
    echo "# You might want to update it anyway:"
    echo "# $ conda env update -n ${mamba_envs[i]} -f ${mamba_envs[i]}.yaml --prune"
  else
    mamba env create --file "${mamba_envs[i]}.yaml"
  fi
done

################################################################
## main
MIGRATE=${1:-false}

function main() {
    ################################################################
    echo "# Setting environment variables."
    source vars.env
    export SECRET_KEY
    export EMAIL_HOST_PASSWORD
    export EMAIL_HOST
    export EMAIL_PORT
    export EMAIL_USE_TLS
    export EMAIL_HOST_USER
    export DEFAULT_FROM_EMAIL
    
    ################################################################
    environment="mgw"
    server=""
    if [[ "$MIGRATE" == "mm" ]]; then
        echo "# Make MGW model migrations."
        command="makemigrations"
        mgw_server environment command server
    fi
    if [[ "$MIGRATE" == "m" || "$MIGRATE" == "mm" ]]; then
        echo "# Migrate MGW models."
        command="migrate"
        mgw_server environment command server
    fi
    
    ################################################################
    echo "# Start MGW server."
    command="runserver"
    server="localhost:8080"
    mgw_server environment command server
}


################################################################
## functions
function mgw_server() {
    local -n arg_one=$1
    local -n arg_two=$2
    local -n arg_tre=$3
    mamba run --live-stream -n ${arg_one} \
    python manage.py ${arg_two} ${arg_tre}
}


################################################################
## call
main
