#!/usr/bin/env bash
# Explicit local candidate builder. Never deploys or pushes.
set -euo pipefail

if [[ "${1:-}" == --help ]]; then
    printf 'Usage: bash images/agent-dev/build.sh [--reuse-install-layers]\n'
    printf 'Builds a fresh LOCAL candidate with Podman, then tests offline and through local SSH.\n'
    printf 'Default: refresh all installation steps. Debug option: reuse matching RUN layers, still pull bases.\n'
    printf 'May download multiple toolchain images and apt/npm packages. No deployment or push.\n'
    exit 0
fi
cache_args=(--no-cache)
install_policy=fresh
if (( $# == 1 )) && [[ "$1" == --reuse-install-layers ]]; then
    cache_args=()
    install_policy=reuse-matching-install-layers
elif (( $# != 0 )); then
    echo 'Only --reuse-install-layers or --help is accepted.' >&2
    exit 2
fi

context=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
umask 077
builds_root="${TMPDIR:-/tmp}/agent-dev-builds"
mkdir -p "$builds_root"
attempt=$(mktemp -d "$builds_root/$(date -u +%Y%m%dT%H%M%SZ)-XXXXXX")
image="localhost/agent-dev:candidate-$(basename "$attempt" | tr '[:upper:]' '[:lower:]')"
printf 'Candidate: %s\nBuild record: %s\n' "$image" "$attempt"
printf 'building\n' > "$attempt/status"
printf '%s\n' "$install_policy" > "$attempt/install-layer-policy"
printf 'Installation policy: %s (base manifests always refreshed)\n' "$install_policy"
on_exit() {
    local code=$?
    if (( code != 0 )); then
        printf 'failed (exit %s); no deployment attempted\n' "$code" > "$attempt/status"
    fi
}
trap on_exit EXIT

# Record all image inputs and host-side checks before starting the build.
(cd "$context" && sha256sum Containerfile sshd_config .containerignore .dockerignore \
    build.sh test-ssh.py scripts/entrypoint.sh scripts/smoke.sh \
    scripts/versions.py scripts/configure-environment.py) > "$attempt/source-sha256.txt"

# Refresh inputs explicitly. Reusing RUN caches would otherwise keep stale apt/npm layers.
podman build --pull=always "${cache_args[@]}" --layers \
    --iidfile "$attempt/image.id" \
    --tag "$image" --file "$context/Containerfile" "$context" \
    2>&1 | tee "$attempt/build.log"
iid=$(< "$attempt/image.id")
podman image inspect "$iid" > "$attempt/image-inspect.json"
podman image inspect \
    docker.io/library/ubuntu:24.04 \
    docker.io/library/python:3-slim-bookworm \
    docker.io/library/node:current-bookworm-slim \
    docker.io/library/golang:bookworm \
    docker.io/library/rust:slim-bookworm > "$attempt/base-images.json"
(cd "$context" && sha256sum -c "$attempt/source-sha256.txt") > "$attempt/source-integrity.log"

# No authentication, host mounts, published ports, or network access.
# Testing with a read-only root also exposes accidental runtime writes.
podman run --rm --network=none --read-only \
    --tmpfs /tmp:rw,exec,nosuid,nodev,mode=1777 --tmpfs /run:rw,nosuid,mode=0755 \
    --entrypoint /bin/bash "$iid" \
    /usr/local/libexec/agent-container/smoke.sh \
    2>&1 | tee "$attempt/offline-smoke.log"
podman run --rm --network=none --read-only --entrypoint /bin/cat "$iid" \
    /usr/local/share/agent-container-versions.json > "$attempt/versions.json"
python3 "$context/test-ssh.py" "sha256:${iid#sha256:}" \
    2> "$attempt/ssh-verification.stderr" | tee "$attempt/ssh-verification.json"
python3 - "$attempt/image-inspect.json" "$attempt/versions.json" "$image" \
    "$attempt/ssh-verification.json" "$install_policy" <<'PY' | tee "$attempt/summary.json"
import json
import sys

with open(sys.argv[1]) as f:
    image = json.load(f)[0]
with open(sys.argv[2]) as f:
    versions = json.load(f)
with open(sys.argv[4]) as f:
    ssh = json.load(f)
assert ssh["status"] == "passed" and ssh["application_tools_passed"]
assert ssh["interactive_login_passed"]
print(json.dumps({
    "candidate": sys.argv[3],
    "image_id": image["Id"],
    "uncompressed_bytes": image["Size"],
    "installation_policy": sys.argv[5],
    "software": versions,
    "offline_smoke_passed": True,
    "ssh_login_tested": True,
    "ssh_verification": ssh,
}, indent=2))
PY
printf 'candidate built; offline/login/SSH/SFTP/recreation checks passed\n' > "$attempt/status"
printf '\nNo registry push or deployment was performed.\n'
