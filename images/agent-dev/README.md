# agent-dev Container Image

Stateless developer toolchain and coding CLI image (`codex`, `opencode`, `pi`, `agy`) built on Ubuntu 24.04 (`C.UTF-8`, `WORKDIR /workspace`) with `/usr/bin/tini` supervising foreground OpenSSH (`sshd -D -e`).

## Toolchain Baseline

- **Python**: Official Python 3 runtime under `/usr/local` with `ruff`, `black`, `mypy`, `isort`, `pytest`, `cpplint`, and `cmakelang`, plus an isolated `/opt/python-tools` venv exposing `uv`, `uvx`, `poetry`, and `pipx`.
- **Node.js**: Current Node runtime under `/opt/node` (`node`, `npm`, `npx`), `/opt/agent-tools` (`pnpm`, `yarn`, `typescript`, `eslint`, `prettier`, `pyright`), and `/opt/corepack-tools` (`corepack`).
- **Go & Rust**: Go toolchain + `golangci-lint` under `/opt/go` and `/opt/go-tools`; Rust toolchain + `rustfmt` and `clippy` under `/opt/rust` and `/opt/rustup`.
- **Native, Shell & CI Utilities**: GCC/G++, Clang (`clang-format`, `clang-tidy`), CMake, Ninja, `ccache`, `protoc`, SWIG, `nasm`, `yasm`, `shellcheck`, `actionlint`, `hadolint`, Git/Git LFS, `ripgrep`, `fd-find`, `jq`, `sqlite3`, `rsync`, `ffmpeg`, CJK fonts, `tmux`, `nano`, `tini`, and OpenSSH server/SFTP.
- **Coding CLIs**: `@openai/codex`, `opencode-ai`, `@earendil-works/pi-coding-agent`, and Antigravity CLI (`agy`).
- **Intentionally Excluded**: Unused runtimes (`swift`, `php`, `java`, `ruby`, `erlang`, `elixir`), multi-version managers (`pyenv`, `nvm`, `mise`), and any project-specific virtual environments or user state.

[configure-environment.py](scripts/configure-environment.py) generates `/etc/profile.d/agent-env.sh`, `/etc/environment`, and `/usr/local/bin` wrappers so tools resolve consistently across `exec`, login shells, and SSH sessions while preserving activated project venvs. Installed versions are recorded once at build time into `/usr/local/share/agent-container-versions.json`.

## Lifecycle, State & Runtime Secrets

- **Immutable program layer**: `.containerignore` and `.dockerignore` share an identical allowlist covering only `Containerfile`, `sshd_config`, and `scripts/`. No credentials, SSH keys, proxies, or user state enter the image.
- **Explicit runtime mounts**: Mount workspaces, `/etc/ssh/ssh_host_ed25519_key` (`entrypoint.sh` refuses to start `sshd` or generate ephemeral host keys if missing), `/root/.ssh/authorized_keys`, and CLI state directories (`/root/.codex`, `/root/.pi`, `/root/.gemini`, `/root/.config/opencode`, `/root/.local/share/opencode`, `/root/.local/state/opencode`, `/root/.cache/opencode`, `/root/.bash_history`) explicitly on the host; mount `/tmp` and `/run` as `tmpfs`.
- **Runtime credentials & proxies**: Inject API credentials at runtime from a host-managed `0400` plain `NAME=value` environment file (without `export` prefixes, startup flags, or command-line secret arguments) and pass deployment proxies via runtime environment or `sshd` `SetEnv`. Drain active interactive or `tmux` work before scheduled container recreation.

## Validation

```bash
bash images/agent-dev/build.sh
```

Every candidate build passes two automated gates:
1. **Offline Toolchain Smoke Test ([smoke.sh](scripts/smoke.sh))**: Runs under `--network=none --read-only` with disposable `/tmp` and `/run` `tmpfs` mounts, verifying language toolchains, linters (`shellcheck`, `actionlint`, `hadolint`, `ruff`, `mypy`, `pyright`), venv `PATH` preservation, login-shell and stripped-`PATH` wrappers, and absence of excluded runtimes.
2. **Isolated SSH, SFTP & Recreation Test ([test-ssh.py](test-ssh.py))**: Boots the candidate image by immutable `sha256` ID with ephemeral Ed25519 keys and `--read-only` root, verifying SSH tool availability, PTY login, read-only `/root` enforcement, SFTP round-trip, and state preservation across container recreation.
