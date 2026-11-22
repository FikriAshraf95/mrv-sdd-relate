# syntax=docker/dockerfile:1
# Stages (SPEC-11 §1, §3):
#   dev      long-running dev container: uv, the Relate CLI, git. The venv and uv cache live in named volumes.
#   build    non-editable install of relate-sdd into /opt/venv
#   runtime  slim image, non-root user sdd (uid 10001), ENTRYPOINT ["sdd"]

ARG PYTHON_IMAGE=python:3.13-slim
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.13

FROM ${UV_IMAGE} AS uv

# ---------------------------------------------------------------- dev
FROM ${PYTHON_IMAGE} AS dev
# openssh-client: the Relate installer verifies its signed SHA256SUMS with ssh-keygen (O9).
RUN apt-get update \
    && apt-get install -y --no-install-recommends git curl ca-certificates openssh-client \
    && rm -rf /var/lib/apt/lists/*
COPY --from=uv /uv /uvx /usr/local/bin/
# Relate CLI (O9, SPEC-00 §8): the relate-db wheel ships no CLI binary, so use the official
# installer. It picks amd64/arm64 from uname and installs into $HOME/.local/bin, so point HOME
# at /opt/relate and link the binary onto PATH.
RUN curl -sSfL https://relatedb.ai/install.sh -o /tmp/relate-install.sh \
    && HOME=/opt/relate sh /tmp/relate-install.sh \
    && ln -s /opt/relate/.local/bin/relate /usr/local/bin/relate \
    && rm /tmp/relate-install.sh \
    && relate --version
# The bind-mounted repo is owned by another user (SPEC-04 §6).
RUN git config --system --add safe.directory '*'
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_CACHE_DIR=/cache/uv \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    SDD_WATCH=poll \
    DO_NOT_TRACK=1 \
    PATH=/opt/venv/bin:$PATH
WORKDIR /workspace
CMD ["sleep", "infinity"]

# ---------------------------------------------------------------- build
FROM ${PYTHON_IMAGE} AS build
COPY --from=uv /uv /usr/local/bin/
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never
WORKDIR /src
COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable

# ---------------------------------------------------------------- runtime
FROM ${PYTHON_IMAGE} AS runtime
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/* \
    && git config --system --add safe.directory '*' \
    && useradd --uid 10001 --create-home --shell /usr/sbin/nologin sdd
COPY --from=build /opt/venv /opt/venv
COPY src /app/src
COPY samples /app/samples
# /data is the demo's working folder (SPEC-11 §2, §7). A named volume mounted there copies this
# ownership on first use, so uid 10001 can write it while the root file system stays read-only.
RUN mkdir -p /data && chown 10001:10001 /data
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    SDD_WATCH=auto
WORKDIR /app
USER 10001
ENTRYPOINT ["sdd"]
CMD ["--help"]
