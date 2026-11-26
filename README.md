# ci-images

Public container image recipes, lockfile snapshots, contract tests, and GitHub Actions build workflows for three pre-baked images published to GitHub Container Registry (GHCR):

| Image | Registry Reference | Base | Contents |
| --- | --- | --- | --- |
| `infra-ci` | `ghcr.io/jerroro/infra-ci` | `ghcr.io/actions/actions-runner:2.338.2` (pinned `@sha256`) | System CI tools (`nftables`, `iproute2`, `jq`, `PyYAML`, `util-linux`), single-user Nix `2.36.0`, and pre-baked upstream `flake.lock` closure (`SQLite` WAL checkpointed for read-only/stateless execution). |
| `mihomo-ci` | `ghcr.io/jerroro/mihomo-ci` | `ghcr.io/actions/actions-runner:2.338.2` (pinned `@sha256`) | SHA-256-verified `uv` `0.9.5`, Python `3.14`, `mihomo` `v1.19.33`, `sops` `v3.11.0`, `Country.mmdb` geodata, offline wheelhouse, and pre-synced locked virtual environment. |
| `agent-dev` | `ghcr.io/jerroro/agent-dev` | `ubuntu:24.04` + multi-stage toolchains | Developer environment with Python, Node, Go, Rust, native C/C++ build tools, coding CLIs, `tini`, and foreground OpenSSH. |

## Repository Layout

```text
images/
  infra-ci/    # Containerfile, strict allowlist ignore files, provision.sh
  mihomo-ci/   # Containerfile, strict allowlist ignore files, provision.sh
  agent-dev/   # Containerfile, scripts, sshd_config, isolated SSH test, docs
locks/
  infra/       # flake.lock snapshot for pre-baking the Nix store closure
  mihomo/      # pyproject.toml, uv.lock, .python-version, geodata.json
tests/
  test_contracts.py
.github/
  workflows/build.yml
```

## Automated Build & Lockfile Refresh Flow

1. **Lockfile Sync**: Downstream consumers push updated lockfile snapshots into `locks/infra/` or `locks/mihomo/` on `main` (or trigger `repository_dispatch` with event type `sync-locks` to rebuild lock snapshots already committed on `main`).
2. **Contract Gate (`contracts` job)**: Runs `python3 -m unittest discover -s tests -v` on `ubuntu-24.04` to validate strict `.containerignore`/`.dockerignore` allowlists, Dockerfile hygiene (no heredocs, pinned base digests), script syntax, and public-repository leak checks.
3. **Parallel Image Builds & Offline Smoke Tests**: Each affected image builds cleanly (`--pull=always --no-cache`) with Podman on `ubuntu-24.04` and passes strict `--network=none --read-only` smoke tests (plus an isolated loopback SSH/SFTP/recreation check for `agent-dev`).
4. **Immutable Publication**: On `main` (non-PR), images are pushed to `ghcr.io/jerroro/<image>` as `:sha-<commit>` and `:latest` (when HEAD is still current on `main`), emitting the immutable `@sha256:<digest>` pin in the workflow summary for downstream consumers and Renovate digest updates.

## Local Contract Verification

```bash
python3 -m unittest discover -s tests -v
```
