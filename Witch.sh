#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

pick_python() {
  if command -v python3 >/dev/null 2>&1; then
    echo python3
    return
  fi
  if command -v python >/dev/null 2>&1; then
    echo python
    return
  fi
  echo "需要 Python 3.10+：https://www.python.org/downloads/" >&2
  exit 1
}

PY="$(pick_python)"
if [[ ! -x .venv/bin/python ]]; then
  "$PY" -m venv .venv
  .venv/bin/python -m pip install -U pip
  .venv/bin/python -m pip install -r requirements.txt
fi
exec .venv/bin/python -m witch
