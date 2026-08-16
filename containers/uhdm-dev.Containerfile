FROM ghcr.io/trv3wood/eda-uhdm:main

USER root

RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
       g++ \
       pkg-config \
    && rm -rf /var/lib/apt/lists/*

ENV PKG_CONFIG_PATH=/opt/conda/envs/uhdm/lib/pkgconfig
