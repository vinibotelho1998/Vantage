#!/usr/bin/env bash
set -eu
root="$(cd -- "$(dirname -- "$0")" && pwd)"
python="$root/.venv/bin/python"
if [[ ! -x "$python" ]]; then python=python3; fi
if ! "$python" -c 'import psutil, PySide6' >/dev/null 2>&1; then
    printf '%s\n' "Instale as dependências no diretório do Vantage:" 'python3 -m venv .venv && .venv/bin/pip install -e .' >&2
    exit 1
fi
export PYTHONPATH="$root/src${PYTHONPATH:+:$PYTHONPATH}"
exec "$python" -m vantage "$@"
