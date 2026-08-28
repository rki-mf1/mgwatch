# syntax=docker/dockerfile:1
FROM ghcr.io/prefix-dev/pixi:0.78.0 AS pixi
FROM debian:bookworm-slim
ARG DEBIAN_FRONTEND=noninteractive
ARG MGWATCH_UID=1000
ARG MGWATCH_GID=1000

COPY --from=pixi /usr/local/bin/pixi /usr/local/bin/pixi

RUN apt update --allow-releaseinfo-change && apt install -y ca-certificates procps wget gzip pigz bc && apt-get clean && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*
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
RUN mkdir -p /code/static /data /logs && \
    chown "${MGWATCH_UID}:${MGWATCH_GID}" /code /code/static /data /logs

ENV PYTHONDONTWRITEBYTECODE=1 \
    XDG_CACHE_HOME=/tmp/.cache \
    PIXI_NO_PROGRESS=true \
    HOME=/home/mgwatch
USER ${MGWATCH_UID}:${MGWATCH_GID}

COPY --chown=${MGWATCH_UID}:${MGWATCH_GID} pixi.toml pixi.lock* .
RUN pixi install --locked
COPY --chown=${MGWATCH_UID}:${MGWATCH_GID} manage.py README.md .coveragerc .
COPY --chown=${MGWATCH_UID}:${MGWATCH_GID} templates/ /code/templates
COPY --chown=${MGWATCH_UID}:${MGWATCH_GID} mgw/ /code/mgw
COPY --chown=${MGWATCH_UID}:${MGWATCH_GID} mgw_api/ /code/mgw_api
RUN DEBUG=True SECRET_KEY=dummy pixi run --locked ./manage.py collectstatic --no-input
