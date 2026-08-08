FROM debian:bookworm

RUN apt-get update && apt-get install -y --no-install-recommends \
    binwalk \
    squashfs-tools \
    python3 \
    python3-pycryptodome \
    atftpd \
    git \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Clone tpconf_bin_xml — commit must be provided via --build-arg
ARG TPCONF_COMMIT
RUN test -n "$TPCONF_COMMIT" || (echo "ERROR: --build-arg TPCONF_COMMIT=... is required" && false)
RUN git clone https://github.com/sta-c0000/tpconf_bin_xml /opt/tpconf_bin_xml \
    && cd /opt/tpconf_bin_xml && git checkout $TPCONF_COMMIT

WORKDIR /work

COPY src/ /opt/patcher/

ENTRYPOINT ["python3", "-u", "/opt/patcher/entrypoint.py"]
