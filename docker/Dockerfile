# GeN-Foam (foamForNuclear) on OpenFOAM v2606, built from source. Both are pinned below.
#
# Build (from this directory, about 90 min on 8 cores):
#   docker build -t genfoam:local .

FROM ubuntu:24.04@sha256:008173c23f95b170204355c12626cb5a965d779a7e1283b09e9cffbb1bf33ca3

ARG OF_VERSION=v2606
ARG OF_SHA256=2a1310e3ed192cc4c521e1d22dcc176f57bec61160c878dc4348f21d6672294d
ARG FFN_REPO=https://gitlab.com/foamForNuclear/foamForNuclear.git
ARG FFN_COMMIT=fc476114d3f7ed45059319b66d1b0ead8b712a16
ARG NCPU=8

ENV DEBIAN_FRONTEND=noninteractive
SHELL ["/bin/bash", "-c"]

# --- system packages (compiler, MPI, system scotch/fftw, python for FFN API) ---
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential cmake flex bison libfl-dev gawk bc \
        zlib1g-dev libreadline-dev libncurses-dev \
        openmpi-bin libopenmpi-dev \
        libscotch-dev libptscotch-dev libfftw3-dev \
        git ca-certificates curl procps less vim-tiny \
        python3 python3-venv python3-pip \
    && rm -rf /var/lib/apt/lists/*

# --- OpenFOAM v2606 from the release tarball ---
# System scotch/fftw; CGAL/boost/kahip/metis/adios2/hdf5 disabled (not used by
# foamForNuclear). Object files are removed afterwards; lnInclude headers stay
# so user code can still be compiled against this install.
RUN set -e; mkdir -p /opt/OpenFOAM && cd /opt/OpenFOAM \
    && curl -fsSL -o OpenFOAM-${OF_VERSION}.tgz \
         https://dl.openfoam.com/source/${OF_VERSION}/OpenFOAM-${OF_VERSION}.tgz \
    && echo "${OF_SHA256}  OpenFOAM-${OF_VERSION}.tgz" | sha256sum -c - \
    && tar xzf OpenFOAM-${OF_VERSION}.tgz && rm OpenFOAM-${OF_VERSION}.tgz \
    && cd OpenFOAM-${OF_VERSION} \
    && bin/tools/foamConfigurePaths \
         -scotch scotch-system -fftw fftw-system \
         -cgal cgal-none -boost boost-none \
         -kahip kahip-none -metis metis-none \
         -adios adios-none -hdf5 hdf5-none; \
    set +e; source etc/bashrc; set -e; \
    ./Allwmake -j ${NCPU} -s -l; \
    test -x "$FOAM_APPBIN/blockMesh"; test -x "$FOAM_APPBIN/foamDictionary"; \
    test -x "$FOAM_APPBIN/decomposePar"; \
    rm -rf build

# --- foamForNuclear (GeN-Foam app) at a pinned commit ---
# Libraries/apps go to the OpenFOAM *site* dirs (not ~/OpenFOAM/<user>-v2606),
# so any container user (root or --user uid:gid) finds them on PATH/LD path.
RUN source /opt/OpenFOAM/OpenFOAM-${OF_VERSION}/etc/bashrc; \
    set -e \
    && git clone ${FFN_REPO} /opt/foamForNuclear \
    && cd /opt/foamForNuclear \
    && git checkout ${FFN_COMMIT} \
    && git log -1 --format='%H %ci %s' > COMMIT \
    && export FOAM_USER_LIBBIN="$FOAM_SITE_LIBBIN" FOAM_USER_APPBIN="$FOAM_SITE_APPBIN" \
    && mkdir -p "$FOAM_SITE_LIBBIN" "$FOAM_SITE_APPBIN" \
    && TERM=dumb ./Allwmake -j ${NCPU} \
    && test -x "$FOAM_SITE_APPBIN/GeN-Foam" \
    && find . -path '*/Make/linux64*' -prune -exec rm -rf {} + \
    && rm -rf .git thirdParty/FMU4FOAM/.git

# --- foamForNuclear Python API (used by some tutorials, e.g. 1D_pipingNetwork mesh.py) ---
RUN python3 -m venv /opt/ffn-venv \
    && /opt/ffn-venv/bin/pip install --no-cache-dir -e /opt/foamForNuclear/pythonapi

# --- runtime ---
# OMPI_* lets mpirun work when the container runs as root (interactive use);
# run.sh runs as the host user instead.
ENV OMPI_ALLOW_RUN_AS_ROOT=1 \
    OMPI_ALLOW_RUN_AS_ROOT_CONFIRM=1 \
    MPLBACKEND=Agg
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod 755 /usr/local/bin/entrypoint.sh \
    && printf 'OpenFOAM %s (tarball sha256 %s)\nfoamForNuclear %s\nbuilt %s\n' \
         "${OF_VERSION}" "${OF_SHA256}" "$(cat /opt/foamForNuclear/COMMIT)" "$(date -u +%FT%TZ)" \
         > /opt/genfoam-build-info.txt

WORKDIR /case
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["bash"]
