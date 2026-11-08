# The norns image for this fork: norns-lab's runtime plus the SuperCollider
# extras that scripts in the pack need (sc3-plugins, Mutable Instruments UGens).
#   docker build -t norns-station norns/container
# Needs the norns-lab runtime image first (github.com/snassen/norns-lab).
ARG BASE=norns-lab-runtime
FROM ${BASE}

ARG DEBIAN_FRONTEND=noninteractive
# The same mi-UGens revision as the Pi 4 add-on; PR 24 adds MiBeads. Its
# build.sh ends by checking for 32-bit ARM (norns hardware) and fails on
# arm64, so the result is checked here instead.
ARG MI_UGENS_REV=8b67db8fd424af7999d783c292e339f59967ee4d
# Must match the supercollider-server package in the base image.
ARG SC_VERSION=Version-3.11.2

USER root
RUN apt-get update && apt-get install -y --no-install-recommends \
    sc3-plugins-language sc3-plugins-server && rm -rf /var/lib/apt/lists/*

USER we
RUN git clone -q https://github.com/carlosedp/norns-mi-UGens.git /tmp/mi \
    && cd /tmp/mi && git checkout -q --detach "$MI_UGENS_REV" \
    && git submodule update -q --init --recursive --depth 1 \
    && (./build.sh --native --pr 24 --sc-version "$SC_VERSION" --work /tmp/mi/work || true) \
    && readelf -h /tmp/mi/work/out/mi-UGens/MiBeads.so | grep -q AArch64 \
    && cp -r /tmp/mi/work/out/mi-UGens /home/we/.local/share/SuperCollider/Extensions/ \
    && rm -rf /tmp/mi

# norns reads its update number from ~/version.txt; without it the version
# is "000000" and scripts that require a recent norns refuse to load
# (dreamsequence, mlre, cheat_codes_2). The pinned norns is newer than
# release v3.0.2 (260819).
RUN echo 260819 > /home/we/version.txt

# The base image's entrypoint starts as root and drops to we.
USER root
