# agent-dev Container Image

Container image providing developer toolchains and coding CLIs (`codex`, `opencode`, `pi`, `agy`) over Ubuntu 24.04 with `tini` and foreground OpenSSH.

## Design Boundaries

- **Immutable program layer**: Toolchains and CLIs live under `/opt` and `/usr/local`. No user state, credentials, SSH keys, or repositories are baked into the image.
- **Explicit runtime state**: Mount workspace directories, SSH host keys (`/etc/ssh/ssh_host_ed25519_key`), authorized keys (`/root/.ssh/authorized_keys`), and CLI state directories explicitly at runtime.
- **Consistent PATH across entry modes**: `scripts/configure-environment.py` generates `/etc/profile.d/agent-env.sh`, `/etc/environment`, and `/usr/local/bin` wrappers so tools remain available in direct `exec`, login shells, and SSH sessions while preserving activated project virtual environments.
- **Build-time inventory**: Installed software versions are captured once during build into `/usr/local/share/agent-container-versions.json`.
- **Strict build context**: `.containerignore` and `.dockerignore` share an identical strict allowlist covering only `Containerfile`, `sshd_config`, and the four scripts under `scripts/`.

## Documentation

- [Tool Baseline](tool-baseline.md)
- [Lifecycle & State Boundaries](lifecycle.md)
- [Runtime Secrets Pattern](runtime-secrets.md)
- [Validation Scope](validation.md)

## Local Build & Verification

```bash
bash images/agent-dev/build.sh
```
