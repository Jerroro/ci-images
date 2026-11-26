# Container Lifecycle & State Boundaries

## Separation of Image and Runtime State

- This image supplies only stateless developer binaries and system packages.
- Workspaces, credentials, shell history, SSH host keys, and CLI databases belong on explicit host-managed bind mounts or volumes, never inside the container's disposable writable layer.
- `entrypoint.sh` validates that `/etc/ssh/ssh_host_ed25519_key` is present before starting `sshd` and refuses to auto-generate ephemeral host identities at startup.

## Process Supervision & Shutdown

- PID 1 is `/usr/bin/tini`, supervising foreground `/usr/sbin/sshd -D -e` and reaping zombie processes.
- Stopping the container signals `sshd` cleanly, but does not automatically drain long-running tasks inside active SSH or `tmux` sessions; drain interactive work before scheduled container replacements.
- Mount `/tmp` and `/run` as `tmpfs` so ephemeral runtime artifacts are discarded on recreation.

## Runtime Proxies

- Network proxies are deployment-specific and are never baked into this image.
- If a deployment requires an HTTP/HTTPS proxy, inject it at runtime through container environment variables or `sshd` configuration without embedding credentials in build inputs or public configuration.
