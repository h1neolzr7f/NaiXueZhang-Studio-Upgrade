#!/usr/bin/env bash
# Idempotent Cloud Agent bootstrap for Nai学长工作室 (FastAPI localhost service).
# Mirrors the core dependency set used by the GitHub Actions `tests` job so the
# server runs and the platform-agnostic test suite passes on Linux.
set -euo pipefail

cd "$(dirname "$0")/.."

# Python 3.12 ships in the base image but the stdlib venv module needs the
# distro `python3.12-venv` package. Install it once; skip when already present.
if ! dpkg -s python3.12-venv >/dev/null 2>&1; then
  sudo DEBIAN_FRONTEND=noninteractive apt-get update -qq
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends python3.12-venv
fi

# Create the virtualenv only when missing so re-runs stay fast and stable.
if [ ! -x ".venv/bin/python" ]; then
  python3 -m venv .venv
fi

.venv/bin/python -m pip install --upgrade pip

# Core profile (matches requirements.core.lock.txt) plus the langgraph packages
# the Butler/Director routes import at startup and the test runner.
.venv/bin/python -m pip install \
  -r requirements.core.lock.txt \
  pytest \
  langgraph \
  langgraph-checkpoint-sqlite

echo "install.sh: environment ready (.venv Python $(.venv/bin/python --version))"
