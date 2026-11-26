#!/usr/bin/env bash
set -euo pipefail

if [[ "${1:-}" == /usr/sbin/sshd ]]; then
    mkdir -p /run/sshd
    if [[ ! -s /etc/ssh/ssh_host_ed25519_key ]]; then
        echo 'Missing persistent SSH host key: /etc/ssh/ssh_host_ed25519_key' >&2
        echo 'Provision and mount it explicitly; startup never creates a new service identity.' >&2
        exit 1
    fi
    /usr/sbin/sshd -t
fi

exec "$@"
