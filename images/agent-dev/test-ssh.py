"""Isolated local SSH/recreation check. Uses only generated test credentials."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tempfile
import time
import uuid


CONTEXT = Path(__file__).resolve().parent


def command(args, *, check=True, input_text=None):
    return subprocess.run(
        args, check=check, capture_output=True, text=True, input=input_text, timeout=60
    )


def proxy_environment(url):
    # This deployment mechanism uses sshd argv: credentials are forbidden.
    if not re.fullmatch(r"https?://[A-Za-z0-9._-]+:[0-9]{1,5}", url):
        raise ValueError("SSH proxy injection requires a credential-free host:port URL.")
    if not 1 <= int(url.rsplit(":", 1)[1]) <= 65535:
        raise ValueError("Invalid proxy port.")
    values = {key: url for key in (
        "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"
    )}
    values["NO_PROXY"] = values["no_proxy"] = "localhost,127.0.0.1,::1,host.containers.internal"
    return values


def verify(image, *, proxy_url=None):
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", image):
        raise ValueError("Pass an exact local image ID, not a mutable tag.")
    proxy = proxy_environment(proxy_url) if proxy_url else {}
    runtime_options = [arg for key, value in sorted(proxy.items())
                       for arg in ("--env", f"{key}={value}")]
    ssh_command = (["/usr/sbin/sshd", "-D", "-e", "-o", "SetEnv=" + " ".join(
        f"{key}={value}" for key, value in sorted(proxy.items())
    )] if proxy else [])
    os.umask(0o077)
    parent = Path(os.environ.get("AGENT_DEV_SSH_CHECK_DIR") or Path(tempfile.gettempdir()) / "agent-dev-ssh-checks")
    parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-")
    work = Path(tempfile.mkdtemp(prefix=stamp, dir=parent))
    for directory in ("sshd", "authorized", "state"):
        (work / directory).mkdir(mode=0o700)
    shutil.copyfile(CONTEXT / "sshd_config", work / "sshd" / "sshd_config")
    for key in (work / "sshd" / "ssh_host_ed25519_key", work / "client"):
        command(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key)])
    shutil.copyfile(work / "client.pub", work / "authorized" / "authorized_keys")
    host_public = (work / "sshd" / "ssh_host_ed25519_key.pub").read_text().split()
    # Application state is explicit, just like the intended deployment. Do not
    # make all of HOME writable to conceal undeclared paths (OpenCode also uses
    # ~/.local/state/opencode, not only its config/share/cache directories).
    app_mounts = {
        "codex": "/root/.codex",
        "pi": "/root/.pi",
        "antigravity": "/root/.gemini",
        "opencode-config": "/root/.config/opencode",
        "opencode-data": "/root/.local/share/opencode",
        "opencode-state": "/root/.local/state/opencode",
        "opencode-cache": "/root/.cache/opencode",
    }
    app_volumes = []
    for source, target in app_mounts.items():
        directory = work / "state" / source
        directory.mkdir(mode=0o700)
        app_volumes.extend(["--volume", f"{directory}:{target}:rw,Z"])
    history = work / "state" / "bash_history"
    history.write_text("")
    app_volumes.extend(["--volume", f"{history}:/root/.bash_history:rw,Z"])
    name = "agent-dev-ssh-check-" + uuid.uuid4().hex[:12]
    result = {
        "image_id": image,
        "application_tools_passed": False,
        "work": str(work),
        "application_state_mounts": [*app_mounts.values(), "/root/.bash_history"],
        "runtime_proxy_requested": bool(proxy),
    }

    def launch():
        command([
            "podman", "run", "--detach", "--pull=never", "--name", name,
            "--label", "io.local.agent-dev.test=ssh",
            "--read-only", "--tmpfs", "/run:rw,nosuid,mode=0755",
            "--tmpfs", "/tmp:rw,nosuid,mode=1777",
            "--publish", "127.0.0.1::22",
            "--volume", f"{work / 'sshd'}:/etc/ssh:ro,Z",
            "--volume", f"{work / 'authorized'}:/root/.ssh:ro,Z",
            "--volume", f"{work / 'state'}:/state:rw,Z",
            *app_volumes, *runtime_options, image, *ssh_command,
        ])
        address = command(["podman", "port", name, "22/tcp"]).stdout.strip()
        if not re.fullmatch(r"127\.0\.0\.1:\d+", address):
            raise RuntimeError(f"Unexpected test listener: {address!r}")
        port = address.rsplit(":", 1)[1]
        known = work / "known_hosts"
        known.write_text(f"[127.0.0.1]:{port} {host_public[0]} {host_public[1]}\n")
        return [
            "ssh", "-F", "/dev/null", "-T", "-p", port,
            "-i", str(work / "client"),
            "-o", "BatchMode=yes", "-o", "IdentitiesOnly=yes",
            "-o", "IdentityAgent=none", "-o", "StrictHostKeyChecking=yes",
            "-o", "UserKnownHostsFile=" + str(known),
            "-o", "GlobalKnownHostsFile=/dev/null",
            "-o", "ConnectTimeout=2", "-o", "LogLevel=ERROR",
            "root@127.0.0.1",
        ]

    def ready(ssh):
        last = None
        for _ in range(20):
            last = command(ssh + ["printf ssh-ready"], check=False)
            if last.returncode == 0 and last.stdout == "ssh-ready":
                return
            time.sleep(0.5)
        raise RuntimeError("Candidate SSH login failed: " + last.stderr.strip())

    try:
        ssh = launch()
        ready(ssh)
        result["ssh_login_passed"] = True
        if proxy:
            code = ("import json,os; print(json.dumps({key:os.environ.get(key) "
                    f"for key in {sorted(proxy)!r}" + "}))")
            direct = command(["podman", "exec", name, "python", "-c", code])
            remote = command(ssh + ["python -c " + shlex.quote(code)])
            if json.loads(direct.stdout) != proxy or json.loads(remote.stdout) != proxy:
                raise RuntimeError("Runtime proxy did not reach direct execution and SSH.")
            result["runtime_proxy_environment_passed"] = True
            response = command(ssh + [
                "curl -fsS --max-time 20 -o /dev/null -w '%{http_code}' "
                "https://www.gstatic.com/generate_204"
            ])
            if response.stdout != "204":
                raise RuntimeError("SSH default proxy request did not return 204.")
            result["ssh_default_proxy_status"] = response.stdout
        tools = command(ssh + [
            "/usr/local/libexec/agent-container/smoke.sh --session"
        ], check=False)
        (work / "ssh-tools.log").write_text(tools.stdout + tools.stderr)
        if tools.returncode:
            raise RuntimeError(
                "Application tools unavailable over SSH: " + tools.stderr.strip()
            )
        result["application_tools_passed"] = True
        interactive_ssh = ["-tt" if arg == "-T" else arg for arg in ssh]
        interactive = command(interactive_ssh, input_text=(
            "set -e\n"
            "/usr/local/libexec/agent-container/smoke.sh --session\n"
            "printf '\\n__AGENT_INTERACTIVE_OK__\\n'\n"
            "exit\n"
        ), check=False)
        (work / "ssh-interactive.log").write_text(interactive.stdout + interactive.stderr)
        if (interactive.returncode or
                "__AGENT_INTERACTIVE_OK__" not in interactive.stdout.splitlines()):
            raise RuntimeError("Interactive SSH login environment failed.")
        result["interactive_login_passed"] = True
        if "smoke.sh --session" not in history.read_text():
            raise RuntimeError("Interactive shell history did not reach its declared mount.")
        result["shell_history_mount_passed"] = True
        command(ssh + [
            "printf persistent-ok > /state/probe; printf transient > /tmp/probe; "
            "printf codex-fixture > /root/.codex/state-probe; "
            "printf opencode-fixture > /root/.local/state/opencode/state-probe"
        ])
        rejected = command(ssh + ["touch /root/undeclared-state"], check=False)
        if rejected.returncode == 0 or "Read-only file system" not in rejected.stderr:
            raise RuntimeError("Read-only root rejection was not confirmed.")
        source, downloaded = work / "upload", work / "download"
        source.write_text("sftp-ok\n")
        sftp = ["sftp", *[arg for arg in ssh[1:-1] if arg != "-T"]]
        sftp[sftp.index("-p")] = "-P"
        sftp.extend(["-b", "-", ssh[-1]])
        command(sftp, input_text=(
            f'put "{source}" /state/sftp-probe\n'
            f'get /state/sftp-probe "{downloaded}"\n'
        ))
        if downloaded.read_bytes() != source.read_bytes():
            raise RuntimeError("SFTP contents did not round trip.")
        result["ssh_login_passed"] = True
        result["sftp_passed"] = True
        result["undeclared_write_rejected"] = True
        (work / "first-container.log").write_text(
            command(["podman", "logs", name], check=False).stderr
        )
        command(["podman", "rm", "--force", name])

        ssh = launch()
        ready(ssh)
        restored = command(ssh + [
            'test ! -e /tmp/probe && test "$(cat /state/sftp-probe)" = sftp-ok '
            '&& test "$(cat /root/.codex/state-probe)" = codex-fixture '
            '&& test "$(cat /root/.local/state/opencode/state-probe)" = opencode-fixture '
            '&& cat /state/probe'
        ])
        if restored.stdout != "persistent-ok":
            raise RuntimeError("Persistent state did not survive recreation.")
        result["recreation_passed"] = True
        result["application_state_recreation_passed"] = True
        result["host_identity_preserved"] = True
        result["tmp_state_discarded"] = True
        result["status"] = "passed"
    except Exception as error:
        result["status"] = "failed"
        result["error"] = str(error)
        raise
    finally:
        logs = command(["podman", "logs", name], check=False)
        (work / "last-container.log").write_text(logs.stdout + logs.stderr)
        command(["podman", "rm", "--force", "--ignore", name], check=False)
        (work / "result.json").write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image_id", help="exact sha256 image ID from a local build")
    parser.add_argument("--proxy-url", help="optional public runtime proxy URL; never credentials")
    args = parser.parse_args()
    verify(args.image_id, proxy_url=args.proxy_url)
