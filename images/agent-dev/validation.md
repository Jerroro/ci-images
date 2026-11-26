# Automated Validation Scope

Every candidate build of `agent-dev` must pass two automated verification stages before publication:

1. **Offline Toolchain Smoke Test (`scripts/smoke.sh`)**
   - Executed with `--network=none --read-only` and disposable `/tmp` + `/run` `tmpfs` mounts.
   - Verifies Python stdlib/extensions, `uv venv` isolation and venv `PATH` preservation, `pytest`, `ruff`, `mypy`, `pyright`, TypeScript compilation (`tsc` + `node`), Go build, Rust compilation (`rustc`, `cargo fmt`, `cargo clippy`), CMake + Ninja + Clang native build, login-shell and stripped-`PATH` wrappers, and absence of excluded runtimes (`swift`, `php`, `java`, `ruby`, `erl`, `elixir`).

2. **Isolated SSH, SFTP & Recreation Test (`test-ssh.py`)**
   - Launches the candidate image by immutable local `sha256` image ID with ephemeral generated Ed25519 keys, `--read-only` root, explicit temporary state mounts, and a random `127.0.0.1` loopback port.
   - Verifies non-interactive SSH tool availability (`smoke.sh --session`), interactive PTY login + shell history mount, rejection of undeclared writes under read-only `/root`, SFTP upload/download round-trip, and full container deletion + recreation preserving mounted state while discarding `/tmp`.
