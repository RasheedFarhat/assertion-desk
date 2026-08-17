# desk/api.py runtime image. Builds only what the Flask app needs to run --
# this is NOT a harness/corpus-regeneration image. Corpus regeneration needs a
# live Keycloak plus Playwright's Chromium download (see Makefile's `corpus`
# target and its own "needs Keycloak running" note) and is a local, explicit,
# occasional operation, never something this container does on start.
#
# Two stages: `builder` compiles the packages that need native extensions
# against python3-saml's C dependencies (xmlsec1/libxml2/openssl bindings via
# python-xmlsec, plus lxml); `runtime` copies only the installed Python
# packages and the shared libraries those extensions dlopen at import time --
# not the -dev headers or the compiler toolchain used to build them.

FROM python:3.13-slim AS builder

# libxmlsec1-openssl is xmlsec1's OpenSSL crypto backend. python3-saml needs
# it present at build time (not just libxmlsec1 itself), or assertion
# decryption/signing fails at import with an opaque xmlsec.InternalError --
# this is a real gotcha, not defensive copy-paste.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        pkg-config \
        libxml2-dev \
        libxmlsec1-dev \
        libxmlsec1-openssl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY requirements.txt .
# --user installs into /root/.local, which the runtime stage copies wholesale.
# Skips reinstalling every package's build step in the final image layer.
RUN pip install --no-cache-dir --user -r requirements.txt

FROM python:3.13-slim AS runtime

# Runtime-only system dependencies: the shared libraries the compiled
# extensions above dlopen, without -dev headers or build-essential.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libxml2 \
        libxmlsec1-openssl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 desk \
    && mkdir -p /data && chown desk:desk /data

COPY --from=builder /root/.local /home/desk/.local

WORKDIR /app
# Targeted COPY, not `COPY . .` -- deliberately excludes tests/, docs/, n8n/,
# harness/, .venv/, .git/, and anything else this image does not run.
# desk/api.py's POST /cases wraps the frozen corpus (see its module
# docstring), so corpus/ and fixtures/ have to ship in the image for that
# demo-scoped intake path to work; harness/ (which regenerates them against a
# live Keycloak) does not.
COPY desk/ desk/
COPY eval/ eval/
COPY corpus/ corpus/
COPY fixtures/ fixtures/

RUN chown -R desk:desk /app

USER desk
ENV PATH=/home/desk/.local/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    DESK_DB_PATH=/data/desk.db \
    PORT=5050

# /data is where DESK_DB_PATH lives. compose.yaml binds a named volume here so
# case state survives a container restart -- not declared as a Docker VOLUME
# here, to keep this Dockerfile equally usable with a plain
# `docker run -v desk-data:/data ...` outside Compose.
EXPOSE 5050

HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=5 \
    CMD python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5050/health', timeout=2)" || exit 1

# desk/api.py's own main() docstring already says this is a Flask dev server,
# not a production WSGI target -- true here too. A gunicorn/uwsgi front end is
# a real follow-up, not something to fake with a fancier CMD line.
CMD ["python3", "-m", "desk.api"]
