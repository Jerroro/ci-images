# ci-images Agent Guidelines

Public repository that builds, smoke-tests, and publishes zero-secret container images (`ghcr.io/jerroro/{infra-ci,mihomo-ci,agent-dev}`) on `ubuntu-24.04` runners.

## Repository Layout

- `images/{infra-ci,mihomo-ci,agent-dev}/`: `Containerfile`, provisioning scripts, and strict `.dockerignore` / `.containerignore` allowlists.
- `locks/infra/` & `locks/mihomo/`: Mirrored public dependency lockfiles synced from downstream repositories to pre-bake offline caches.
- `tests/test_contracts.py`: Static contract, allowlist parity, and leak checks.
- `.github/workflows/build.yml`: Contract gate, parallel Podman builds, `--network=none --read-only` smoke tests, and GHCR publication.

## Verification Commands

```bash
python3 -m unittest discover -s tests -v
shellcheck images/*/*.sh
actionlint .github/workflows/*.yml
hadolint images/*/Containerfile
```

## Hard Constraints

- **Public-repo zero-leak boundary**: Never include credentials, tokens, private URLs, internal IP addresses, private hostnames, or topology details in files, comments, commit messages, or image layers.
- **Podman / Buildah compatibility**: Do not use Dockerfile heredocs (`RUN <<EOF`); keep `.dockerignore` and `.containerignore` byte-identical in each image directory.
- **Deterministic & offline-ready images**: Pin external tool downloads by SHA-256; do not manually edit mirrored files under `locks/` (they are updated from upstream lockfiles); preserve `--network=none --read-only` smoke-test compatibility (including checkpointing Nix SQLite WAL before finalizing `infra-ci`).
- **First-principles implementation**: Derive build steps directly from container/OS primitives and standard linters (`shellcheck`, `actionlint`, `hadolint`) for a single-maintainer setup; replace obsolete scaffolding directly rather than layering defensive wrappers.
