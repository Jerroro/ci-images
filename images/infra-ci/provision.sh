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

ACTIONLINT_VERSION="1.7.12"
case "$(uname -s).$(uname -m)" in
  Linux.x86_64)
    ACTIONLINT_ARCH="amd64"
    ACTIONLINT_TAR_SHA256="8aca8db96f1b94770f1b0d72b6dddcb1ebb8123cb3712530b08cc387b349a3d8"
    ACTIONLINT_BIN_SHA256="c872d6db8c6bf83a8eaa704fc93999f027d55dffbc63b8a6abdccb47df5f4cd4"
    ;;
  Linux.aarch64)
    ACTIONLINT_ARCH="arm64"
    ACTIONLINT_TAR_SHA256="325e971b6ba9bfa504672e29be93c24981eeb1c07576d730e9f7c8805afff0c6"
    ACTIONLINT_BIN_SHA256="ac0323433c2853ec3fb978c611430c5b3dc5d43c58d1a1ec031b00ab572beb60"
    ;;
  *)
    echo "ERROR: unsupported platform for actionlint: $(uname -s).$(uname -m)" >&2
    exit 1
    ;;
esac
ACTIONLINT_TAR_URL="https://github.com/rhysd/actionlint/releases/download/v${ACTIONLINT_VERSION}/actionlint_${ACTIONLINT_VERSION}_linux_${ACTIONLINT_ARCH}.tar.gz"
ACTIONLINT_BIN="${INFRA_CI_ACTIONLINT_BIN:-/usr/local/bin/actionlint}"

check_sha256() {
  local file="$1" expected="$2"
  [[ -f "$file" ]] || return 1
  printf '%s  %s\n' "$expected" "$file" | sha256sum --status -c - 2>/dev/null
}

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
shellcheck --version >/dev/null 2>&1 || packages+=(shellcheck)

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

if ! ([[ -x "$ACTIONLINT_BIN" ]] && check_sha256 "$ACTIONLINT_BIN" "$ACTIONLINT_BIN_SHA256"); then
  if ((verify_only)); then
    echo "Missing or mismatched actionlint binary: ${ACTIONLINT_BIN}" >&2
    exit 1
  fi
  tmp_dir="$(mktemp -d)"
  trap '[[ -n "${tmp_dir:-}" ]] && rm -rf "$tmp_dir"' EXIT
  curl --fail --silent --show-error --location \
    --retry 5 --retry-all-errors --connect-timeout 20 --max-time 180 \
    --output "${tmp_dir}/actionlint.tar.gz" "$ACTIONLINT_TAR_URL"
  printf '%s  %s\n' "$ACTIONLINT_TAR_SHA256" "${tmp_dir}/actionlint.tar.gz" | sha256sum -c - >/dev/null
  tar -xzf "${tmp_dir}/actionlint.tar.gz" -C "$tmp_dir" actionlint
  printf '%s  %s\n' "$ACTIONLINT_BIN_SHA256" "${tmp_dir}/actionlint" | sha256sum -c - >/dev/null
  as_root install -D -m 0755 "${tmp_dir}/actionlint" "$ACTIONLINT_BIN"
  rm -rf "$tmp_dir"
  trap - EXIT
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
command -v shellcheck >/dev/null 2>&1
shellcheck --version >/dev/null
[[ -x "$ACTIONLINT_BIN" ]] && check_sha256 "$ACTIONLINT_BIN" "$ACTIONLINT_BIN_SHA256"
"$ACTIONLINT_BIN" -version >/dev/null
