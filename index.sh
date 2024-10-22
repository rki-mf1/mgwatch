#!/usr/bin/env bash

################################################################
#mamba
mamba_envs=("mgw")
if command -v mamba &> /dev/null; then echo "# Mamba is installed."; else echo "# Mamba is not installed."; echo "# Please download and install Miniforge3:"; echo '#     curl -L -O "https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-$(uname)-$(uname -m).sh"'; echo '#     bash Miniforge3-$(uname)-$(uname -m).sh'; exit; fi
for i in "${!mamba_envs[@]}"
do
    if mamba info --envs | grep -q ${mamba_envs[i]}; then echo "# Mamba environment ${mamba_envs[i]} already exists."; else mamba env create --file ${mamba_envs[i]}.yaml; fi
done


################################################################
## main
function main() {

    ################################################################
    echo "# Starting MetagenomeWatch server."
    environment="mgw"
    address=""
    command="create_index"
    mgw_server environment command address
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
