# Developer Toolchain Baseline

Single-version developer toolchains layered onto Ubuntu 24.04 (`C.UTF-8`, `WORKDIR /workspace`):

## Included

- **Python**: Official Python 3 runtime under `/usr/local` with `ruff`, `black`, `mypy`, `isort`, `pytest`, `cpplint`, `cmakelang`, plus isolated `/opt/python-tools` venv exposing `uv`, `uvx`, `poetry`, and `pipx`.
- **Node.js**: Current Node runtime under `/opt/node` (`node`, `npm`, `npx`), `/opt/agent-tools` (`pnpm`, `yarn`, `typescript`, `eslint`, `prettier`, `pyright`), and isolated `/opt/corepack-tools` (`corepack`).
- **Go & Rust**: Official Go toolchain + `golangci-lint` under `/opt/go` and `/opt/go-tools`; Rust toolchain + `rustfmt` and `clippy` under `/opt/rust` and `/opt/rustup`.
- **Native & CLI utilities**: GCC/G++, Clang (`clang-format`, `clang-tidy`), CMake, Ninja, `ccache`, `protoc`, SWIG, `nasm`, `yasm`, Git/Git LFS, `ripgrep`, `fd-find`, `jq`, `sqlite3`, `rsync`, `ffmpeg`, CJK fonts, `tmux`, `nano`, `tini`, and OpenSSH server/SFTP.
- **Coding CLIs**: `@openai/codex`, `opencode-ai`, `@earendil-works/pi-coding-agent`, and Antigravity CLI (`agy`) installed under `/opt`.

## Excluded

- Unused language ecosystems (`swift`, `php`, `java`, `ruby`, `erlang`, `elixir`) and multi-version managers (`pyenv`, `nvm`, `mise`).
- Project-specific dependencies and virtual environments (managed per project via lockfiles).
- Any user credentials, host keys, proxies, or personal state.

## Explicit Writable State Mounts Tested Under Read-Only Root

- `/root/.codex`
- `/root/.pi`
- `/root/.gemini`
- `/root/.config/opencode`
- `/root/.local/share/opencode`
- `/root/.local/state/opencode`
- `/root/.cache/opencode`
- `/root/.bash_history`
