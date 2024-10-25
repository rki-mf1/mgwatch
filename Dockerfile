FROM continuumio/miniconda3:24.7.1-0
ARG DEBIAN_FRONTEND=noninteractive

RUN apt update --allow-releaseinfo-change && apt install -y procps wget gzip pigz bc cron && apt-get clean && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

WORKDIR /code
COPY manage.py README.md mgw.yaml vars.env .
COPY mgw/ /code/mgw
COPY mgw_api/ /code/mgw_api
COPY templates/ /code/templates
RUN conda env create -n mgw -f mgw.yaml
