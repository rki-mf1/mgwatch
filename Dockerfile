FROM condaforge/miniforge3:24.11.3-0
ARG DEBIAN_FRONTEND=noninteractive

RUN apt update --allow-releaseinfo-change && apt install -y procps wget gzip pigz bc cron && apt-get clean && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

WORKDIR /code
COPY mgw.yaml .
RUN conda env create -n mgw -f mgw.yaml && conda clean --all -y
COPY manage.py README.md vars.env .
COPY templates/ /code/templates
COPY mgw/ /code/mgw
COPY mgw_api/ /code/mgw_api
