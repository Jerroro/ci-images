#!/usr/bin/env bash
# Run with --network=none, without production mounts or authentication.
set -euo pipefail

# Lightweight probe shared by login and both SSH session types. Full versions
# are recorded once at image build time, not rescanned in every session.
case "${1:-}" in
    --session)
        python -c 'import sys, pytest; assert sys.prefix == sys.base_prefix, sys.executable'
        node --version
        go version
        rustc --version
        cargo --version
        uv --version
        shellcheck --version >/dev/null
        actionlint -version >/dev/null
        hadolint --version >/dev/null
        codex --version
        opencode --version
        pi --version
        agy --version
        exit 0 ;;
    "") ;;
    *) echo 'Usage: smoke.sh [--session]' >&2; exit 2 ;;
esac

work=$(mktemp -d)
trap 'rm -rf -- "$work"' EXIT
export HOME="$work/home"
export CARGO_HOME="$HOME/.cargo"
export GOPATH="$HOME/go"
export GOCACHE="$HOME/.cache/go-build"
export XDG_CACHE_HOME="$HOME/.cache"
export XDG_CONFIG_HOME="$HOME/.config"
export XDG_DATA_HOME="$HOME/.local/share"
export UV_PYTHON_DOWNLOADS=never
export COREPACK_ENABLE_NETWORK=0
mkdir -p "$HOME"
cd "$work"

python -c 'import sys, ssl, sqlite3, ctypes, bz2, lzma, readline, dbm.gnu, uuid, pytest; assert sys.prefix == sys.base_prefix, sys.executable; print("Python", sys.version.split()[0])'
cargo fmt --version
cargo clippy --version
ffmpeg -version >/dev/null
/usr/sbin/sshd -V

# Both login-shell profile and completely stripped default PATH must work.
bash --login -c 'exec /usr/local/libexec/agent-container/smoke.sh --session'
env -i HOME="$HOME" PATH=/usr/local/bin:/usr/bin:/bin node --version
env -i HOME="$HOME" PATH=/usr/local/bin:/usr/bin:/bin cargo --version
env -i HOME="$HOME" PATH=/usr/local/bin:/usr/bin:/bin go version

uv venv --python /usr/local/bin/python --no-python-downloads "$work/venv"
"$work/venv/bin/python" -c 'import sys; assert sys.prefix != sys.base_prefix'
env -i HOME="$HOME" PATH="$work/venv/bin:/usr/local/bin:/usr/bin:/bin" \
    node -e 'if (!process.env.PATH.startsWith(process.argv[1])) throw Error("venv PATH lost")' "$work/venv/bin"
cat > test_sample.py <<'PY'
def add(a: int, b: int) -> int:
    return a + b


def test_add() -> None:
    assert add(1, 2) == 3
PY
python -m pytest -q test_sample.py
ruff check test_sample.py
mypy test_sample.py
pyright test_sample.py

printf 'const value: number = 42; console.log(value);\n' > hello.ts
tsc --target es2020 --skipLibCheck hello.ts
test "$(node hello.js)" = 42
printf 'package main\nimport "fmt"\nfunc main(){fmt.Println("go-ok")}\n' > hello.go
GO111MODULE=off go build -o hello-go hello.go
test "$(./hello-go)" = go-ok
printf 'fn main() { println!("rust-ok"); }\n' > hello.rs
rustc hello.rs -o hello-rust
test "$(./hello-rust)" = rust-ok

mkdir native
printf 'int main(void) { return 0; }\n' > native/hello.c
printf 'cmake_minimum_required(VERSION 3.16)\nproject(smoke C)\nadd_executable(hello hello.c)\n' > native/CMakeLists.txt
cmake -S native -B native-build -G Ninja
cmake --build native-build
./native-build/hello
clang native/hello.c -o hello-clang
./hello-clang

# One selected development toolchain, not the universal multi-version bundle.
# Ubuntu may also retain its system Python for apt-managed OS tools.
test "$(find /opt/rustup/toolchains -mindepth 1 -maxdepth 1 -type d | wc -l)" -eq 1
for command in swift php java javac ruby erl elixir; do
    if command -v "$command" >/dev/null 2>&1; then
        echo "Unexpected excluded runtime: $command" >&2
        exit 1
    fi
done
printf '\nOffline developer, login-shell and stripped-environment checks passed. SSH login and mount migration remain separate checks.\n'
