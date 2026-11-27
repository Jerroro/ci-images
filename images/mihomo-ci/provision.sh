#!/usr/bin/env bash
# Authoritative CI tool & public GeoIP provisioner for the mihomo-ci runner image.
set -euo pipefail
umask 022

UV_VERSION="0.9.5"
UV_TAR_URL="https://github.com/astral-sh/uv/releases/download/${UV_VERSION}/uv-x86_64-unknown-linux-gnu.tar.gz"
UV_TAR_SHA256="2cf10babba653310606f8b49876cfb679928669e7ddaa1fb41fb00ce73e64f66"
UV_BIN_SHA256="d3dc3ca8e29337dd602a9a4df9e6edb15ebc52aed91461debeedb96939dc4ce0"

PYTHON_SERIES="3.14"
UV_PYTHON_ROOT="/usr/local/share/uv/python"

MIHOMO_VERSION="v1.19.33"
MIHOMO_GZ_URL="https://github.com/MetaCubeX/mihomo/releases/download/${MIHOMO_VERSION}/mihomo-linux-amd64-v1-${MIHOMO_VERSION}.gz"
MIHOMO_GZ_SHA256="8ec92e7b2fdc6b853ba00156bab7e4e965c8b0d843b8c4ac8ab98795f02ad524"
MIHOMO_BIN_SHA256="19cbe7ba1523a92ed2d0a30716ea093de57db05b7844db23de2b9c21fd7a1afa"

SOPS_VERSION="v3.11.0"
SOPS_URL="https://github.com/getsops/sops/releases/download/${SOPS_VERSION}/sops-${SOPS_VERSION}.linux.amd64"
SOPS_BIN_SHA256="775f1384d55decfad228e7196a3f683791914f92a473f78fc47700531c29dfef"

ACTIONLINT_VERSION="v1.7.12"
ACTIONLINT_TAR_URL="https://github.com/rhysd/actionlint/releases/download/${ACTIONLINT_VERSION}/actionlint_${ACTIONLINT_VERSION#v}_linux_amd64.tar.gz"
ACTIONLINT_TAR_SHA256="8aca8db96f1b94770f1b0d72b6dddcb1ebb8123cb3712530b08cc387b349a3d8"
ACTIONLINT_BIN_SHA256="c872d6db8c6bf83a8eaa704fc93999f027d55dffbc63b8a6abdccb47df5f4cd4"

INSTALL_BIN_DIR="/usr/local/bin"
GEODATA_DIR="/usr/share/mihomo-config/geodata"

as_root() {
  if [[ "$(id -u)" -eq 0 ]]; then
    "$@"
  else
    sudo -n "$@"
  fi
}

check_sha256() {
  local file="$1" expected="$2"
  [[ -f "$file" ]] || return 1
  printf '%s  %s\n' "$expected" "$file" | sha256sum --status -c - 2>/dev/null
}

fetch_file() {
  local url="$1" dest="$2"
  curl --fail --silent --show-error --location \
    --retry 4 --retry-delay 2 --retry-all-errors --connect-timeout 20 --max-time 180 \
    --output "$dest" "$url"
}

if [[ "${RUNNER_ENVIRONMENT:-}" == "github-hosted" ]]; then
  unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY no_proxy NO_PROXY
  if [[ -n "${GITHUB_ENV:-}" ]]; then
    for var in http_proxy https_proxy HTTP_PROXY HTTPS_PROXY no_proxy NO_PROXY; do
      printf '%s=\n' "$var" >> "$GITHUB_ENV"
    done
  fi
  if [[ -e /proc/sys/kernel/apparmor_restrict_unprivileged_userns ]]; then
    as_root sysctl -w kernel.apparmor_restrict_unprivileged_userns=0 || true
  fi
fi

export PATH="${INSTALL_BIN_DIR}:$PATH:/usr/sbin:/sbin"

missing_pkgs=()
[[ -s /etc/ssl/certs/ca-certificates.crt ]] || missing_pkgs+=(ca-certificates)
command -v curl >/dev/null 2>&1 || missing_pkgs+=(curl)
command -v git >/dev/null 2>&1 || missing_pkgs+=(git)
command -v unshare >/dev/null 2>&1 || missing_pkgs+=(util-linux)
command -v ip >/dev/null 2>&1 || missing_pkgs+=(iproute2)
command -v gzip >/dev/null 2>&1 || missing_pkgs+=(gzip)
command -v tar >/dev/null 2>&1 || missing_pkgs+=(tar)
command -v shellcheck >/dev/null 2>&1 || missing_pkgs+=(shellcheck)

if ((${#missing_pkgs[@]} > 0)); then
  apt_opts=(-o "Acquire::Retries=5" -o "Acquire::http::Pipeline-Depth=0")
  if [[ -n "${http_proxy:-}" ]]; then
    apt_opts+=(-o "Acquire::http::Proxy=${http_proxy}")
  fi
  if [[ -n "${https_proxy:-}" ]]; then
    apt_opts+=(-o "Acquire::https::Proxy=${https_proxy}")
  fi
  for attempt in 1 2 3 4; do
    if as_root env DEBIAN_FRONTEND=noninteractive apt-get "${apt_opts[@]}" update; then
      break
    fi
    [[ "$attempt" -lt 4 ]] || exit 1
    sleep 2
  done
  for attempt in 1 2 3 4; do
    if as_root env DEBIAN_FRONTEND=noninteractive apt-get "${apt_opts[@]}" install -y --no-install-recommends "${missing_pkgs[@]}"; then
      break
    fi
    [[ "$attempt" -lt 4 ]] || exit 1
    sleep 2
  done
  if [[ "${CLEAN_APT_LISTS:-0}" == "1" ]]; then
    as_root rm -rf /var/lib/apt/lists/*
  fi
fi

export SSL_CERT_FILE="/etc/ssl/certs/ca-certificates.crt"

tmp_dir=""
ensure_tmp() {
  if [[ -z "$tmp_dir" ]]; then
    tmp_dir="$(mktemp -d)"
    trap '[[ -n "${tmp_dir:-}" ]] && rm -rf "$tmp_dir"' EXIT
  fi
}

if ! check_sha256 "${INSTALL_BIN_DIR}/uv" "$UV_BIN_SHA256"; then
  ensure_tmp
  fetch_file "$UV_TAR_URL" "$tmp_dir/uv.tar.gz"
  check_sha256 "$tmp_dir/uv.tar.gz" "$UV_TAR_SHA256" || {
    echo "ERROR: uv archive SHA-256 mismatch" >&2
    exit 1
  }
  tar -xzf "$tmp_dir/uv.tar.gz" -C "$tmp_dir"
  check_sha256 "$tmp_dir/uv-x86_64-unknown-linux-gnu/uv" "$UV_BIN_SHA256" || {
    echo "ERROR: extracted uv binary SHA-256 mismatch" >&2
    exit 1
  }
  as_root install -D -m 0755 "$tmp_dir/uv-x86_64-unknown-linux-gnu/uv" "${INSTALL_BIN_DIR}/uv"
fi

if ! (command -v python3.14 >/dev/null 2>&1 && python3.14 -c 'import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 14) else 1)' 2>/dev/null); then
  as_root install -d -m 0755 "$UV_PYTHON_ROOT"
  as_root env \
    UV_PYTHON_INSTALL_DIR="$UV_PYTHON_ROOT" \
    SSL_CERT_FILE="$SSL_CERT_FILE" \
    http_proxy="${http_proxy:-}" \
    https_proxy="${https_proxy:-}" \
    no_proxy="${no_proxy:-}" \
    "${INSTALL_BIN_DIR}/uv" python install "$PYTHON_SERIES"
  as_root chmod -R a+rX "$UV_PYTHON_ROOT"
  py314="$(UV_PYTHON_INSTALL_DIR="$UV_PYTHON_ROOT" "${INSTALL_BIN_DIR}/uv" python find --no-project "$PYTHON_SERIES")"
  [[ -x "$py314" ]] || {
    echo "ERROR: Python ${PYTHON_SERIES} executable not found after installation" >&2
    exit 1
  }
  as_root ln -sf "$py314" "${INSTALL_BIN_DIR}/python3.14"
fi

if ! check_sha256 "${INSTALL_BIN_DIR}/mihomo" "$MIHOMO_BIN_SHA256"; then
  ensure_tmp
  fetch_file "$MIHOMO_GZ_URL" "$tmp_dir/mihomo.gz"
  check_sha256 "$tmp_dir/mihomo.gz" "$MIHOMO_GZ_SHA256" || {
    echo "ERROR: mihomo archive SHA-256 mismatch" >&2
    exit 1
  }
  gzip -dc "$tmp_dir/mihomo.gz" > "$tmp_dir/mihomo"
  check_sha256 "$tmp_dir/mihomo" "$MIHOMO_BIN_SHA256" || {
    echo "ERROR: uncompressed mihomo binary SHA-256 mismatch" >&2
    exit 1
  }
  as_root install -D -m 0755 "$tmp_dir/mihomo" "${INSTALL_BIN_DIR}/mihomo"
fi

if ! check_sha256 "${INSTALL_BIN_DIR}/sops" "$SOPS_BIN_SHA256"; then
  ensure_tmp
  fetch_file "$SOPS_URL" "$tmp_dir/sops"
  check_sha256 "$tmp_dir/sops" "$SOPS_BIN_SHA256" || {
    echo "ERROR: sops binary SHA-256 mismatch" >&2
    exit 1
  }
  as_root install -D -m 0755 "$tmp_dir/sops" "${INSTALL_BIN_DIR}/sops"
fi

if ! check_sha256 "${INSTALL_BIN_DIR}/actionlint" "$ACTIONLINT_BIN_SHA256"; then
  ensure_tmp
  fetch_file "$ACTIONLINT_TAR_URL" "$tmp_dir/actionlint.tar.gz"
  check_sha256 "$tmp_dir/actionlint.tar.gz" "$ACTIONLINT_TAR_SHA256" || {
    echo "ERROR: actionlint archive SHA-256 mismatch" >&2
    exit 1
  }
  tar -xzf "$tmp_dir/actionlint.tar.gz" -C "$tmp_dir" actionlint
  check_sha256 "$tmp_dir/actionlint" "$ACTIONLINT_BIN_SHA256" || {
    echo "ERROR: extracted actionlint binary SHA-256 mismatch" >&2
    exit 1
  }
  as_root install -D -m 0755 "$tmp_dir/actionlint" "${INSTALL_BIN_DIR}/actionlint"
fi

if [[ "${SKIP_GEODATA:-0}" != "1" ]]; then
  script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  manifest="${GEODATA_MANIFEST:-}"
  if [[ -z "$manifest" ]]; then
    if [[ -f "./geodata.json" ]]; then
      manifest="./geodata.json"
    elif [[ -f "${script_dir}/../../../geodata.json" ]]; then
      manifest="${script_dir}/../../../geodata.json"
    elif [[ -f "${script_dir}/geodata.json" ]]; then
      manifest="${script_dir}/geodata.json"
    else
      echo "ERROR: geodata.json not found; set GEODATA_MANIFEST or run from repository root" >&2
      exit 1
    fi
  fi

  mapfile -t geo_meta < <(python3.14 - "$manifest" <<'PY'
import json, pathlib, re, sys
source = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
file_name = source["file"]
sha256 = source["sha256"]
url = source["url"]
assert pathlib.Path(file_name).name == file_name and file_name not in ("", ".", ".."), "invalid geodata filename"
assert re.fullmatch(r"[0-9a-f]{64}", sha256), "invalid geodata sha256"
assert url.startswith("https://"), "geodata URL must use https://"
print(file_name)
print(sha256)
print(url)
PY
  )
  geo_file="${geo_meta[0]}"
  geo_sha256="${geo_meta[1]}"
  geo_url="${geo_meta[2]}"
  geo_dest="${GEODATA_DIR}/${geo_file}"

  if ! check_sha256 "$geo_dest" "$geo_sha256"; then
    ensure_tmp
    fetch_file "$geo_url" "$tmp_dir/$geo_file"
    geo_size="$(wc -c < "$tmp_dir/$geo_file")"
    if (( geo_size > 33554432 )); then
      echo "ERROR: downloaded geodata exceeds 32 MiB ceiling (${geo_size} bytes)" >&2
      exit 1
    fi
    check_sha256 "$tmp_dir/$geo_file" "$geo_sha256" || {
      echo "ERROR: geodata (${geo_file}) SHA-256 mismatch" >&2
      exit 1
    }
    as_root install -D -m 0644 "$tmp_dir/$geo_file" "$geo_dest"
  fi
fi

"${INSTALL_BIN_DIR}/uv" --version >/dev/null
python3.14 -c 'import sys; assert sys.version_info[:2] == (3, 14)'
"${INSTALL_BIN_DIR}/mihomo" -v >/dev/null
"${INSTALL_BIN_DIR}/sops" --disable-version-check --version >/dev/null
command -v shellcheck >/dev/null 2>&1
shellcheck --version >/dev/null
"${INSTALL_BIN_DIR}/actionlint" -version >/dev/null

if [[ -n "${GITHUB_PATH:-}" ]]; then
  printf '%s\n' "$INSTALL_BIN_DIR" >> "$GITHUB_PATH"
fi

if [[ -n "${GITHUB_ENV:-}" ]]; then
  printf '%s\n' \
    "MIHOMO_CONFIG_VALIDATOR=${INSTALL_BIN_DIR}/mihomo" \
    "MIHOMO_SOPS_BIN=${INSTALL_BIN_DIR}/sops" \
    "MIHOMO_CONFIG_DATA_DIR=${GEODATA_DIR}" \
    "UV_PYTHON_INSTALL_DIR=${UV_PYTHON_ROOT}" \
    "UV_PYTHON_DOWNLOADS=never" \
    "SSL_CERT_FILE=${SSL_CERT_FILE}" >> "$GITHUB_ENV"
fi
