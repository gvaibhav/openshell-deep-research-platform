# The builder must supply a previously reviewed immutable Python 3.13.x slim
# trixie base ref. The exact digest must pass the current image CVE gate.
ARG PYTHON_BASE_IMAGE
FROM ${PYTHON_BASE_IMAGE}

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/opt/spike \
    PIP_NO_CACHE_DIR=1

COPY requirements-worker.lock /tmp/requirements-worker.lock
RUN python -m pip install --require-hashes --no-cache-dir -r /tmp/requirements-worker.lock \
    && python -m pip uninstall --yes pip \
    && python -c 'from pathlib import Path; import shutil, sysconfig; shutil.rmtree(Path(sysconfig.get_path("stdlib")) / "ensurepip")' \
    && python -c 'import importlib.util, sys; sys.exit(0 if all(importlib.util.find_spec(name) is None for name in ("pip", "ensurepip")) else 1)' \
    && rm /tmp/requirements-worker.lock

RUN groupadd --gid 1000 spike && useradd --uid 1000 --gid 1000 --home-dir /work --create-home spike \
    && mkdir -p /opt/spike/fixtures && chown -R 1000:1000 /work
COPY --chown=1000:1000 spike /opt/spike/spike
COPY --chown=1000:1000 fixtures /opt/spike/fixtures

WORKDIR /work
USER 1000:1000
CMD ["/usr/local/bin/python3.13", "-m", "spike.worker", "--help"]
