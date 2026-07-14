# syntax=docker/dockerfile:1
FROM condaforge/miniforge3:26.3.2-3
ARG DEBIAN_FRONTEND=noninteractive
ARG MGWATCH_UID=1000
ARG MGWATCH_GID=1000

RUN apt update --allow-releaseinfo-change && apt install -y procps wget gzip pigz bc cron && apt-get clean && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*
RUN if ! getent group "${MGWATCH_GID}" >/dev/null; then \
        groupadd --gid "${MGWATCH_GID}" mgwatch; \
    fi && \
    if ! getent passwd "${MGWATCH_UID}" >/dev/null; then \
        useradd --uid "${MGWATCH_UID}" --gid "${MGWATCH_GID}" --create-home --home-dir /home/mgwatch --shell /usr/sbin/nologin mgwatch; \
    else \
        mkdir -p /home/mgwatch; \
        chown "${MGWATCH_UID}:${MGWATCH_GID}" /home/mgwatch; \
    fi

WORKDIR /code
COPY environment.yml .
RUN conda env create --quiet --name mgw --file environment.yml && conda clean --all --yes
COPY manage.py README.md .
COPY templates/ /code/templates
COPY mgw/ /code/mgw
COPY mgw_api/ /code/mgw_api
RUN DEBUG=True SECRET_KEY=dummy conda run --no-capture-output -n mgw ./manage.py collectstatic --no-input
RUN mkdir -p /code/static /data /data-db /logs /var/spool/cron/crontabs && \
    chown -R "${MGWATCH_UID}:${MGWATCH_GID}" /code /data /data-db /logs /var/spool/cron/crontabs

ENV PYTHONDONTWRITEBYTECODE=1 \
    XDG_CACHE_HOME=/tmp/.cache \
    HOME=/home/mgwatch
USER ${MGWATCH_UID}:${MGWATCH_GID}
