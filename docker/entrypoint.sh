#!/bin/bash
# Source the OpenFOAM v2606 environment + foamForNuclear Python venv, then run
# the given command (default: interactive bash).
# HOME/USER may be unset when run as --user uid:gid without a passwd entry.
export HOME="${HOME:-/tmp}"
[ -w "$HOME" ] || export HOME=/tmp
export USER="${USER:-$(id -un 2>/dev/null || echo user)}"
# bashrc reads any "$@" as settings: clear the arguments before sourcing it, restore them after.
args=("$@"); set --
source /opt/OpenFOAM/OpenFOAM-v2606/etc/bashrc || true
set -- "${args[@]}"
export PATH="/opt/ffn-venv/bin:$PATH"
exec "$@"
