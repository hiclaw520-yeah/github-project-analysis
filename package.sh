#!/bin/sh
# Unix entry. Cross-platform logic lives in scripts/package.py.
# Windows: double-click package.cmd  or  python scripts/package.py
cd "$(dirname "$0")" || exit 1
command -v python3 >/dev/null 2>&1 && exec python3 scripts/package.py "$@"
exec python scripts/package.py "$@"
