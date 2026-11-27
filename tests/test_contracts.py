"""Minimal repository contract tests complementing shellcheck, actionlint, and hadolint."""

from __future__ import annotations

from pathlib import Path
import re
import unittest

REPO_ROOT = Path(__file__).resolve().parents[1]
CONTAINERFILES = (
    REPO_ROOT / "images/infra-ci/Containerfile",
    REPO_ROOT / "images/mihomo-ci/Containerfile",
    REPO_ROOT / "images/agent-dev/Containerfile",
)
EXPECTED_IGNORE_RULES: dict[str, list[str]] = {
    "images/infra-ci": ["*", "**", "!Containerfile"],
    "images/mihomo-ci": ["*", "**", "!Containerfile"],
    "images/agent-dev": [
        "*",
        "**",
        "!Containerfile",
        "!sshd_config",
        "!scripts/",
        "scripts/**",
        "!scripts/entrypoint.sh",
        "!scripts/smoke.sh",
        "!scripts/versions.py",
        "!scripts/configure-environment.py",
    ],
}

HOME_PATH_RE = re.compile(r"/home/([A-Za-z0-9._-]+)")
ALLOWED_HOME_USERS = frozenset({"runner", "dev"})
SOURCE_LABEL_RE = re.compile(r"org\.opencontainers\.image\.source=([^\s\"']+)")
FORBIDDEN_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("RFC1918 10.x IPv4", re.compile(r"\b10\.(?:\d{1,3}\.){2}\d{1,3}\b")),
    ("RFC1918 192.168.x IPv4", re.compile(r"\b192\.168\.\d{1,3}\.\d{1,3}\b")),
    ("RFC1918 172.16-31.x IPv4", re.compile(r"\b172\.(?:1[6-9]|2\d|3[0-1])\.\d{1,3}\.\d{1,3}\b")),
    ("CGNAT 100.64-127.x IPv4", re.compile(r"\b100\.(?:6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.\d{1,3}\.\d{1,3}\b")),
    ("Private .arpa domain", re.compile(r"[A-Za-z0-9-]+\.arpa\b", re.IGNORECASE)),
    ("Personal /Users path", re.compile(r"/Users/[a-zA-Z0-9._-]+")),
    ("Host /srv path", re.compile(r"(?<![A-Za-z0-9_])/srv/")),
    ("Runtime /run/secrets path", re.compile(r"/run/secrets/")),
    ("Hardcoded proxy URL", re.compile(r"(?:http|https|all)_proxy\s*=\s*['\"]?https?://", re.IGNORECASE)),
    ("Foreign Jerroro GitHub repo", re.compile(r"github\.com/Jerroro/(?!ci-images\b)[A-Za-z0-9._-]+", re.IGNORECASE)),
    ("Foreign Jerroro repo shorthand", re.compile(r"(?<!users/)\bJerroro/(?!ci-images\b)[A-Za-z0-9._-]+")),
    ("Foreign GHCR image", re.compile(r"ghcr\.io/jerroro/(?!(?:infra-ci|mihomo-ci|agent-dev|\$\{pkg\})\b)[A-Za-z0-9._-]+", re.IGNORECASE)),
    ("GitHub classic PAT", re.compile(r"\bgh[pou]_[A-Za-z0-9]{20,}\b")),
    ("GitHub fine-grained PAT", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b")),
    ("Age private key", re.compile(r"AGE-SECRET-KEY-")),
    ("PEM private key", re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----")),
)


def _iter_repo_files() -> list[Path]:
    return [
        path
        for path in sorted(REPO_ROOT.rglob("*"))
        if path.is_file() and not {".git", "__pycache__"}.intersection(path.relative_to(REPO_ROOT).parts)
    ]


def _scan_text_for_hygiene_violations(rel: str, text: str) -> list[str]:
    violations: list[str] = []
    for match in HOME_PATH_RE.finditer(text):
        if match.group(1) not in ALLOWED_HOME_USERS:
            line_no = text.count("\n", 0, match.start()) + 1
            violations.append(f"{rel}:{line_no}: matched Personal /home path")
    for label, pattern in FORBIDDEN_PATTERNS:
        for match in pattern.finditer(text):
            line_no = text.count("\n", 0, match.start()) + 1
            violations.append(f"{rel}:{line_no}: matched {label}")
    for match in SOURCE_LABEL_RE.finditer(text):
        if match.group(1) != "https://github.com/Jerroro/ci-images":
            line_no = text.count("\n", 0, match.start()) + 1
            violations.append(f"{rel}:{line_no}: non-canonical org.opencontainers.image.source label")
    return violations


class RepositoryContractTests(unittest.TestCase):
    def test_build_context_ignore_files_match_exact_minimal_allowlist(self) -> None:
        for rel_dir, expected_rules in EXPECTED_IGNORE_RULES.items():
            ctx = REPO_ROOT / rel_dir
            c_ignore = ctx / ".containerignore"
            d_ignore = ctx / ".dockerignore"
            self.assertTrue(c_ignore.is_file(), f"Missing {c_ignore}")
            self.assertTrue(d_ignore.is_file(), f"Missing {d_ignore}")
            self.assertEqual(
                c_ignore.read_bytes(),
                d_ignore.read_bytes(),
                f".containerignore and .dockerignore differ in {rel_dir}",
            )
            rules = [
                line.strip()
                for line in c_ignore.read_text(encoding="utf-8").splitlines()
                if line.strip() and not line.lstrip().startswith("#")
            ]
            self.assertEqual(rules, expected_rules, f"Unexpected allowlist rules in {rel_dir}")

    def test_containerfiles_forbid_heredocs_for_buildah_133_parity(self) -> None:
        for path in CONTAINERFILES:
            self.assertNotIn("<<", path.read_text(encoding="utf-8"), f"Dockerfile heredoc forbidden in {path}")

    def test_home_path_allowlist_rejects_suffixed_usernames_without_echoing_matches(self) -> None:
        self.assertEqual(_scan_text_for_hygiene_violations("ok.txt", "/home/runner/run.sh /home/dev/work"), [])
        for bad_sample, forbidden_token in (
            ("/home/dev-build/src", "dev-build"),
            ("/home/runner.local/bin", "runner.local"),
            ("/home/alice/key", "alice"),
        ):
            findings = _scan_text_for_hygiene_violations("sample.txt", bad_sample)
            self.assertEqual(findings, ["sample.txt:1: matched Personal /home path"])
            self.assertNotIn(forbidden_token, findings[0])

    def test_no_private_ips_domains_paths_tokens_or_foreign_repo_urls(self) -> None:
        self_path = Path(__file__).resolve()
        violations: list[str] = []
        for path in _iter_repo_files():
            if path.resolve() == self_path:
                continue
            rel = str(path.relative_to(REPO_ROOT))
            violations.extend(_scan_text_for_hygiene_violations(rel, path.read_text(encoding="utf-8")))
        self.assertEqual(violations, [], "Public-repo hygiene violations:\n" + "\n".join(violations))


if __name__ == "__main__":
    unittest.main()
