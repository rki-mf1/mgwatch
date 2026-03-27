# syntax=docker/dockerfile:1
FROM condaforge/miniforge3:25.11.0-0
ARG DEBIAN_FRONTEND=noninteractive

RUN apt update --allow-releaseinfo-change && apt install -y procps wget gzip pigz bc cron && apt-get clean && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

WORKDIR /code
COPY environment.yml .
RUN conda env create --quiet --name mgw --file environment.yml && conda clean --all --yes
COPY manage.py README.md .
COPY templates/ /code/templates
COPY mgw/ /code/mgw
COPY mgw_api/ /code/mgw_api
RUN SECRET_KEY=dummy conda run --no-capture-output -n mgw ./manage.py collectstatic --no-input
