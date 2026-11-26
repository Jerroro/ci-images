"""Repository contract, syntax, build-context, and public-hygiene tests."""

from __future__ import annotations

import ast
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tempfile
import tomllib
import unittest

try:
    import yaml
except ImportError:  # pragma: no cover - optional on minimal python3 environments
    yaml = None


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = REPO_ROOT / ".github/workflows/build.yml"
CONTAINERFILES = (
    REPO_ROOT / "images/infra-ci/Containerfile",
    REPO_ROOT / "images/mihomo-ci/Containerfile",
    REPO_ROOT / "images/agent-dev/Containerfile",
)
SHELL_SCRIPTS = (
    REPO_ROOT / "images/infra-ci/provision.sh",
    REPO_ROOT / "images/mihomo-ci/provision.sh",
    REPO_ROOT / "images/agent-dev/build.sh",
    REPO_ROOT / "images/agent-dev/scripts/entrypoint.sh",
    REPO_ROOT / "images/agent-dev/scripts/smoke.sh",
)


def _iter_repo_files() -> list[Path]:
    files: list[Path] = []
    for path in sorted(REPO_ROOT.rglob("*")):
        if not path.is_file():
            continue
        rel_parts = path.relative_to(REPO_ROOT).parts
        if ".git" in rel_parts or "__pycache__" in rel_parts:
            continue
        files.append(path)
    return files


def _check_ignored(ignore_file: Path, rel_path: str) -> bool:
    with tempfile.TemporaryDirectory() as td:
        work = Path(td)
        shutil.copyfile(ignore_file, work / ".gitignore")
        subprocess.run(["git", "init", "-q"], cwd=work, check=True)
        res = subprocess.run(["git", "check-ignore", "-q", "--no-index", rel_path], cwd=work)
        return res.returncode == 0


def _logical_dockerfile_lines(content: str) -> list[str]:
    logical: list[str] = []
    buf = ""
    for raw_line in content.splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            if not buf:
                continue
        if raw_line.rstrip().endswith("\\"):
            buf += raw_line.rstrip()[:-1] + " "
        else:
            buf += raw_line
            if buf.strip():
                logical.append(buf.strip())
            buf = ""
    if buf.strip():
        raise AssertionError("Trailing dangling line continuation in Containerfile")
    return logical


class BuildContextAllowlistTests(unittest.TestCase):
    def test_ci_runner_contexts_allowlist_only_containerfile(self) -> None:
        for rel_dir in ("images/infra-ci", "images/mihomo-ci"):
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

            with tempfile.TemporaryDirectory() as td:
                work = Path(td)
                shutil.copyfile(c_ignore, work / ".gitignore")
                subprocess.run(["git", "init", "-q"], cwd=work, check=True)

                allowed_rc = subprocess.run(
                    ["git", "check-ignore", "-q", "--no-index", "Containerfile"], cwd=work
                ).returncode
                self.assertEqual(allowed_rc, 1, f"Containerfile unexpectedly ignored in {rel_dir}")

                for blocked in (
                    "sub/Containerfile",
                    "provision.sh",
                    "flake.lock",
                    "geodata.json",
                    "pyproject.toml",
                    "uv.lock",
                    ".env",
                    "token.txt",
                    "README.md",
                ):
                    rc = subprocess.run(
                        ["git", "check-ignore", "-q", "--no-index", blocked], cwd=work
                    ).returncode
                    self.assertEqual(rc, 0, f"{blocked} unexpectedly allowed in {rel_dir}")

    def test_agent_dev_context_allowlist_is_strict(self) -> None:
        ctx = REPO_ROOT / "images/agent-dev"
        c_ignore = ctx / ".containerignore"
        d_ignore = ctx / ".dockerignore"
        self.assertTrue(c_ignore.is_file())
        self.assertTrue(d_ignore.is_file())
        self.assertEqual(c_ignore.read_bytes(), d_ignore.read_bytes())

        allowed = (
            "Containerfile",
            "sshd_config",
            "scripts/entrypoint.sh",
            "scripts/smoke.sh",
            "scripts/versions.py",
            "scripts/configure-environment.py",
        )
        blocked = (
            "README.md",
            "build.sh",
            "test-ssh.py",
            "lifecycle.md",
            "runtime-secrets.md",
            "tool-baseline.md",
            "validation.md",
            "scripts/secret.sh",
            "scripts/extra.py",
            ".env",
            "sub/Containerfile",
        )
        with tempfile.TemporaryDirectory() as td:
            work = Path(td)
            shutil.copyfile(c_ignore, work / ".gitignore")
            subprocess.run(["git", "init", "-q"], cwd=work, check=True)
            for rel in allowed:
                rc = subprocess.run(
                    ["git", "check-ignore", "-q", "--no-index", rel], cwd=work
                ).returncode
                self.assertEqual(rc, 1, f"{rel} unexpectedly ignored in images/agent-dev")
            for rel in blocked:
                rc = subprocess.run(
                    ["git", "check-ignore", "-q", "--no-index", rel], cwd=work
                ).returncode
                self.assertEqual(rc, 0, f"{rel} unexpectedly allowed in images/agent-dev")


class ContainerfileContractTests(unittest.TestCase):
    def test_no_dockerfile_heredocs_and_valid_instructions(self) -> None:
        valid_keywords = {
            "ARG", "CMD", "COPY", "ENTRYPOINT", "ENV", "EXPOSE",
            "FROM", "LABEL", "RUN", "USER", "WORKDIR",
        }
        for path in CONTAINERFILES:
            content = path.read_text(encoding="utf-8")
            self.assertNotIn("<<", content, f"Dockerfile heredoc forbidden in {path}")
            for line in _logical_dockerfile_lines(content):
                keyword = line.split(None, 1)[0]
                self.assertIn(keyword, valid_keywords, f"Invalid instruction in {path}: {line[:60]!r}")

    def test_infra_ci_containerfile_contract(self) -> None:
        content = (REPO_ROOT / "images/infra-ci/Containerfile").read_text(encoding="utf-8")
        self.assertRegex(
            content,
            r"(?m)^FROM\s+ghcr\.io/actions/actions-runner:2\.338\.2@sha256:[0-9a-f]{64}\b",
        )
        self.assertIn('NIX_VERSION="2.36.0"', content)
        self.assertIn("/nix/var/nix/gcroots/infra-ci-seed", content)
        self.assertIn("PRAGMA wal_checkpoint(TRUNCATE)", content)
        self.assertIn("PRAGMA journal_mode=DELETE", content)
        self.assertIn("USER runner", content)

    def test_mihomo_ci_containerfile_contract(self) -> None:
        content = (REPO_ROOT / "images/mihomo-ci/Containerfile").read_text(encoding="utf-8")
        self.assertRegex(
            content,
            r"(?m)^FROM\s+ghcr\.io/actions/actions-runner:2\.338\.2@sha256:[0-9a-f]{64}\b",
        )
        self.assertIn("COPY --from=setup provision.sh", content)
        self.assertIn("COPY --from=geodata geodata.json", content)
        self.assertIn("COPY --from=lock pyproject.toml uv.lock .python-version", content)
        self.assertIn("/usr/local/share/mihomo-ci/wheelhouse", content)
        self.assertIn("/usr/local/share/mihomo-ci/uv.lock.sha256", content)
        self.assertIn('"--offline"', content)
        self.assertIn('"--no-index"', content)
        self.assertIn('"--require-hashes"', content)
        self.assertIn("USER runner", content)

        # Parse the embedded wheelhouse builder Python script to verify syntax.
        py_lines = re.findall(r"^\s+'(.*)'\s+\\$", content, re.MULTILINE)
        self.assertGreater(len(py_lines), 20, "Failed to extract embedded Python script")
        ast.parse("\n".join(py_lines))


class LockfileAndSyntaxTests(unittest.TestCase):
    def test_lockfiles_parse_cleanly(self) -> None:
        flake_lock = json.loads((REPO_ROOT / "locks/infra/flake.lock").read_text(encoding="utf-8"))
        self.assertEqual(flake_lock.get("version"), 7)
        self.assertIn("nixpkgs", flake_lock.get("nodes", {}))

        geodata = json.loads((REPO_ROOT / "locks/mihomo/geodata.json").read_text(encoding="utf-8"))
        self.assertTrue(geodata["url"].startswith("https://"))
        self.assertRegex(geodata["sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(Path(geodata["file"]).name, geodata["file"])

        pyproject = tomllib.loads((REPO_ROOT / "locks/mihomo/pyproject.toml").read_text(encoding="utf-8"))
        self.assertIn("project", pyproject)

        uv_lock = tomllib.loads((REPO_ROOT / "locks/mihomo/uv.lock").read_text(encoding="utf-8"))
        self.assertGreater(len(uv_lock.get("package", [])), 0)

        py_ver = (REPO_ROOT / "locks/mihomo/.python-version").read_text(encoding="utf-8").strip()
        self.assertRegex(py_ver, r"^3\.\d+$")

    def test_shell_scripts_syntax_and_permissions(self) -> None:
        for script in SHELL_SCRIPTS:
            self.assertTrue(script.is_file(), f"Missing script {script}")
            mode = script.stat().st_mode
            self.assertTrue(mode & stat.S_IXUSR, f"Script is not executable: {script}")
            res = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True)
            self.assertEqual(res.returncode, 0, f"bash -n failed for {script}: {res.stderr}")

    def test_python_files_syntax(self) -> None:
        for path in sorted(REPO_ROOT.rglob("*.py")):
            if ".git" in path.parts:
                continue
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    def test_workflow_contract_and_shell_syntax(self) -> None:
        text = WORKFLOW_PATH.read_text(encoding="utf-8")
        self.assertIn("runs-on: ubuntu-24.04", text)
        self.assertIn("pull_request:", text)
        self.assertIn("repository_dispatch:", text)
        self.assertIn("sync-locks", text)
        self.assertIn("workflow_dispatch:", text)
        self.assertIn("--network=none", text)
        self.assertIn("--read-only", text)
        self.assertIn("org.opencontainers.image.source=https://github.com/Jerroro/ci-images", text)
        self.assertIn("PUBLISHED_DIGEST=", text)
        self.assertNotIn("permission_denied", text, "Push failures must fail hard now that GHCR Write access is granted")

        if yaml is not None:
            doc = yaml.safe_load(text)
            self.assertIsInstance(doc, dict)
            jobs = doc.get("jobs", {})
            self.assertEqual(set(jobs.keys()), {"contracts", "infra-ci", "mihomo-ci", "agent-dev"})
            for job_name, job in jobs.items():
                self.assertEqual(job.get("runs-on"), "ubuntu-24.04", f"Job {job_name} must use ubuntu-24.04")
                for idx, step in enumerate(job.get("steps", [])):
                    run_body = step.get("run")
                    if not run_body:
                        continue
                    res = subprocess.run(
                        ["bash", "-n"],
                        input=run_body,
                        capture_output=True,
                        text=True,
                    )
                    self.assertEqual(
                        res.returncode,
                        0,
                        f"bash -n failed in {job_name} step #{idx + 1} ({step.get('name')}): {res.stderr}",
                    )

    @unittest.skipIf(yaml is None, "PyYAML required to execute workflow publish step stubs")
    def test_publish_steps_fail_hard_on_revision_and_latest_push_errors(self) -> None:
        doc = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
        jobs = doc["jobs"]
        sample_sha = "1" * 40
        sample_digest = "sha256:" + ("a" * 64)

        for job_name in ("infra-ci", "mihomo-ci", "agent-dev"):
            push_steps = [
                step for step in jobs[job_name]["steps"]
                if str(step.get("name", "")).startswith("Push ")
            ]
            self.assertEqual(len(push_steps), 1, f"Expected single Push step in {job_name}")
            run_body = push_steps[0]["run"]

            for fail_on in ("revision", "latest"):
                with tempfile.TemporaryDirectory() as td:
                    tmp = Path(td)
                    bin_dir = tmp / "bin"
                    bin_dir.mkdir()
                    summary = tmp / "summary.md"
                    summary.write_text("", encoding="utf-8")

                    sudo_stub = bin_dir / "sudo"
                    sudo_stub.write_text(
                        "#!/usr/bin/env bash\n"
                        'if [[ "${1:-}" == "-n" ]]; then shift; fi\n'
                        'exec "$@"\n',
                        encoding="utf-8",
                    )
                    sudo_stub.chmod(0o755)

                    git_stub = bin_dir / "git"
                    git_stub.write_text(
                        "#!/usr/bin/env bash\n"
                        'if [[ "${1:-}" == "ls-remote" ]]; then\n'
                        f'  printf "%s\\trefs/heads/main\\n" "{sample_sha}"\n'
                        "  exit 0\n"
                        "fi\n"
                        "exit 1\n",
                        encoding="utf-8",
                    )
                    git_stub.chmod(0o755)

                    podman_stub = bin_dir / "podman"
                    podman_stub.write_text(
                        "#!/usr/bin/env bash\n"
                        "set -euo pipefail\n"
                        'subcmd="${1:-}"; shift || true\n'
                        'case "$subcmd" in\n'
                        "  login|tag)\n"
                        "    cat >/dev/null || true\n"
                        "    exit 0\n"
                        "    ;;\n"
                        "  push)\n"
                        '    digestfile=""\n'
                        '    if [[ "${1:-}" == "--digestfile" ]]; then\n'
                        '      digestfile="$2"; shift 2\n'
                        "    fi\n"
                        '    ref="${1:-}"\n'
                        '    if [[ "$ref" == *":sha-"* ]]; then\n'
                        '      if [[ "${STUB_FAIL_ON}" == "revision" ]]; then\n'
                        '        echo "Error: received unexpected HTTP status: 403 Forbidden" >&2\n'
                        "        exit 125\n"
                        "      fi\n"
                        '      [[ -n "$digestfile" ]] && printf "%s\\n" "${STUB_DIGEST}" > "$digestfile"\n'
                        "      exit 0\n"
                        '    elif [[ "$ref" == *":latest" ]]; then\n'
                        '      if [[ "${STUB_FAIL_ON}" == "latest" ]]; then\n'
                        '        echo "Error: received unexpected HTTP status: 403 Forbidden" >&2\n'
                        "        exit 125\n"
                        "      fi\n"
                        "      exit 0\n"
                        "    fi\n"
                        "    exit 1\n"
                        "    ;;\n"
                        "  *)\n"
                        "    exit 1\n"
                        "    ;;\n"
                        "esac\n",
                        encoding="utf-8",
                    )
                    podman_stub.chmod(0o755)

                    env = {
                        "PATH": f"{bin_dir}:/usr/bin:/bin",
                        "HOME": str(tmp),
                        "GH_TOKEN": "stub-token",
                        "GITHUB_ACTOR": "stub-actor",
                        "GITHUB_SHA": sample_sha,
                        "GITHUB_STEP_SUMMARY": str(summary),
                        "STUB_FAIL_ON": fail_on,
                        "STUB_DIGEST": sample_digest,
                    }
                    res = subprocess.run(
                        ["bash", "-euo", "pipefail"],
                        input=run_body,
                        env=env,
                        capture_output=True,
                        text=True,
                    )
                    self.assertNotEqual(
                        res.returncode,
                        0,
                        f"{job_name} push step must fail hard when {fail_on} push fails",
                    )
                    self.assertNotIn(
                        "PUBLISHED_DIGEST=",
                        res.stdout,
                        f"{job_name} push step emitted PUBLISHED_DIGEST on {fail_on} failure",
                    )
                    self.assertNotIn(
                        "PUBLISHED_DIGEST=",
                        summary.read_text(encoding="utf-8"),
                    )


HOME_PATH_RE = re.compile(r"/home/([A-Za-z0-9._-]+)")
ALLOWED_HOME_USERS = frozenset({"runner", "dev"})


def _scan_text_for_hygiene_violations(
    rel: str,
    text: str,
) -> list[str]:
    forbidden_patterns = (
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
    source_label_re = re.compile(r"org\.opencontainers\.image\.source=([^\s\"']+)")

    violations: list[str] = []
    for match in HOME_PATH_RE.finditer(text):
        if match.group(1) not in ALLOWED_HOME_USERS:
            line_no = text.count("\n", 0, match.start()) + 1
            violations.append(f"{rel}:{line_no}: matched Personal /home path")
    for label, pattern in forbidden_patterns:
        for match in pattern.finditer(text):
            line_no = text.count("\n", 0, match.start()) + 1
            violations.append(f"{rel}:{line_no}: matched {label}")
    for match in source_label_re.finditer(text):
        if match.group(1) != "https://github.com/Jerroro/ci-images":
            line_no = text.count("\n", 0, match.start()) + 1
            violations.append(
                f"{rel}:{line_no}: non-canonical org.opencontainers.image.source label"
            )
    return violations


class PublicRepoHygieneTests(unittest.TestCase):
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
            text = path.read_text(encoding="utf-8")
            violations.extend(_scan_text_for_hygiene_violations(rel, text))

        self.assertEqual(violations, [], "Public-repo hygiene violations:\n" + "\n".join(violations))


if __name__ == "__main__":
    unittest.main()
