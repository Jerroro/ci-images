"""Record the selected development-tool baseline; never read user state."""

import json
from pathlib import Path
import platform
import subprocess
import sys


COMMANDS = {
    "python": ["python", "--version"],
    "node": ["node", "--version"],
    "npm": ["npm", "--version"],
    "pnpm": ["pnpm", "--version"],
    "yarn": ["yarn", "--version"],
    "corepack": ["corepack", "--version"],
    "typescript": ["tsc", "--version"],
    "eslint": ["eslint", "--version"],
    "prettier": ["prettier", "--version"],
    "pyright": ["pyright", "--version"],
    "uv": ["uv", "--version"],
    "poetry": ["poetry", "--version"],
    "pipx": ["pipx", "--version"],
    "ruff": ["ruff", "--version"],
    "black": ["black", "--version"],
    "mypy": ["mypy", "--version"],
    "isort": ["isort", "--version-number"],
    "pytest": ["pytest", "--version"],
    "go": ["go", "version"],
    "golangci_lint": ["golangci-lint", "version"],
    "rust": ["rustc", "--version"],
    "cargo": ["cargo", "--version"],
    "clang": ["clang", "--version"],
    "clang_format": ["clang-format", "--version"],
    "clang_tidy": ["clang-tidy", "--version"],
    "cmake": ["cmake", "--version"],
    "ninja": ["ninja", "--version"],
    "ccache": ["ccache", "--version"],
    "protoc": ["protoc", "--version"],
    "git_lfs": ["git-lfs", "--version"],
    "codex": ["codex", "--version"],
    "opencode": ["opencode", "--version"],
    "pi": ["pi", "--version"],
    "antigravity": ["agy", "--version"],
}


def versions():
    result = {"architecture": platform.machine(), "versions": {}}
    for name, command in COMMANDS.items():
        try:
            completed = subprocess.run(
                command, check=True, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True, timeout=60,
            )
        except subprocess.CalledProcessError as error:
            print(f"Version check failed for {name}: {error.stderr}", file=sys.stderr)
            raise
        output = completed.stdout.strip()
        if not output:
            raise RuntimeError(f"Empty version output for {name}")
        result["versions"][name] = output.splitlines()[0]
    info = Path("/opt/go-tools/build-info.txt")
    if info.is_file():
        result["golangci_lint_build_info"] = info.read_text()
    return result


if __name__ == "__main__":
    print(json.dumps(versions(), indent=2, sort_keys=True))
