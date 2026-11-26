#!/usr/bin/env bash
# Authoritative CI tool & environment provisioner for the infra-ci runner image.
# Used both during image build (pre-bake + offline check) and at runtime verification.
set -euo pipefail
umask 022

verify_only=0
if [[ "${1:-}" == "--verify-only" ]]; then
  verify_only=1
  shift
fi
if (($# > 0)); then
  echo "Usage: provision.sh [--verify-only]" >&2
  exit 2
fi

proc_status_path="${INFRA_CI_PROC_STATUS_PATH:-/proc/self/status}"

no_new_privs() {
  [[ -r "$proc_status_path" ]] && grep -q '^NoNewPrivs:[[:space:]]*1$' "$proc_status_path"
}

is_protected_mode() {
  no_new_privs
}

if ((!verify_only)) && is_protected_mode; then
  verify_only=1
fi

as_root() {
  if is_protected_mode; then
    echo "ERROR: privilege escalation forbidden in NoNewPrivs mode (refusing to invoke sudo)" >&2
    exit 1
  elif [[ "$(id -u)" -eq 0 ]]; then
    "$@"
  else
    sudo -n "$@"
  fi
}

python3_bin="${INFRA_CI_PYTHON3:-/usr/bin/python3}"
ca_bundle="${INFRA_CI_CA_BUNDLE:-/etc/ssl/certs/ca-certificates.crt}"
apparmor_userns_knob="${INFRA_CI_APPARMOR_USERNS_PATH:-/proc/sys/kernel/apparmor_restrict_unprivileged_userns}"

if ((!verify_only)); then
  if [[ "${RUNNER_ENVIRONMENT:-}" == "github-hosted" ]]; then
    if [[ -n "${GITHUB_ENV:-}" ]]; then
      for var in http_proxy https_proxy HTTP_PROXY HTTPS_PROXY no_proxy NO_PROXY; do
        if [[ -n "${!var:-}" ]]; then
          printf '%s=\n' "$var" >> "$GITHUB_ENV"
        fi
      done
    fi
    unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY no_proxy NO_PROXY
    # Ubuntu 24.04+ restricts unprivileged userns by default, blocking single-user
    # (--no-daemon) Nix sandboxes and isolated netns checks on hosted VMs.
    if [[ -e "$apparmor_userns_knob" ]]; then
      current_knob="$(tr -d '[:space:]' < "$apparmor_userns_knob" 2>/dev/null || true)"
      if [[ "$current_knob" != "0" ]]; then
        as_root sysctl -qw kernel.apparmor_restrict_unprivileged_userns=0
      fi
    fi
  fi
fi

packages=()
[[ -s "$ca_bundle" ]] || packages+=(ca-certificates)
command -v curl >/dev/null 2>&1 || packages+=(curl)
command -v git >/dev/null 2>&1 || packages+=(git)
command -v tar >/dev/null 2>&1 || packages+=(tar)
command -v xz >/dev/null 2>&1 || packages+=(xz-utils)
command -v jq >/dev/null 2>&1 || packages+=(jq)
"$python3_bin" -c 'import yaml' >/dev/null 2>&1 || packages+=(python3 python3-yaml)
PATH="$PATH:/usr/sbin:/sbin" command -v nft >/dev/null 2>&1 || packages+=(nftables)
PATH="$PATH:/usr/sbin:/sbin" command -v ip >/dev/null 2>&1 || packages+=(iproute2)
(command -v unshare >/dev/null 2>&1 && command -v nsenter >/dev/null 2>&1) || packages+=(util-linux)

if ((${#packages[@]} > 0)); then
  if ((verify_only)); then
    echo "Missing preinstalled infra-ci packages: ${packages[*]}" >&2
    exit 1
  fi
  apt_opts=()
  if [[ "${RUNNER_ENVIRONMENT:-}" != "github-hosted" ]]; then
    if [[ -n "${http_proxy:-}" ]]; then
      apt_opts+=(-o "Acquire::http::Proxy=${http_proxy}")
    fi
    if [[ -n "${https_proxy:-}" ]]; then
      apt_opts+=(-o "Acquire::https::Proxy=${https_proxy}")
    fi
  fi
  as_root env DEBIAN_FRONTEND=noninteractive apt-get "${apt_opts[@]}" update
  as_root env DEBIAN_FRONTEND=noninteractive apt-get "${apt_opts[@]}" install -y --no-install-recommends "${packages[@]}"
  if [[ "${CLEAN_APT_LISTS:-0}" == "1" ]]; then
    as_root rm -rf /var/lib/apt/lists/*
  fi
fi

[[ -s "$ca_bundle" ]]
command -v curl >/dev/null 2>&1
command -v git >/dev/null 2>&1
command -v tar >/dev/null 2>&1
command -v xz >/dev/null 2>&1
command -v jq >/dev/null 2>&1
"$python3_bin" -c 'import yaml' >/dev/null 2>&1
PATH="$PATH:/usr/sbin:/sbin" command -v nft >/dev/null 2>&1
PATH="$PATH:/usr/sbin:/sbin" command -v ip >/dev/null 2>&1
command -v unshare >/dev/null 2>&1
command -v nsenter >/dev/null 2>&1
