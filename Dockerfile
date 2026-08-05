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

# Clone tpconf_bin_xml at pinned commit
ARG TPCONF_COMMIT=65463c4f3e745eead24d8dff41c35a76927f56bb
RUN git clone https://github.com/sta-c0000/tpconf_bin_xml /opt/tpconf_bin_xml \
    && cd /opt/tpconf_bin_xml && git checkout $TPCONF_COMMIT

WORKDIR /work

COPY src/ /opt/patcher/

ENTRYPOINT ["python3", "/opt/patcher/entrypoint.py"]

