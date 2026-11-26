# Runtime Secrets Pattern

Runtime API keys and credentials are never stored in this repository, build context, or published container image.

## Recommended Delivery

- Provide runtime secrets from a host-managed environment file (mode `0400`, outside the container image and repository).
- Use plain `NAME=value` entries (one per line, without shell `export` prefixes or extra quotes) containing only the variables required by developer tools.
- Do not mix `PATH`, proxy overrides, or startup flags into secret environment files.
- When forwarding variables into SSH sessions, forward only declared variable names from the container environment rather than embedding secret values into command-line arguments.

## Security & Rotation Notes

- Containers sharing a root user do not isolate secrets from processes running as `root` inside the container; avoid printing full environments (`env`, `sshd -T`, or `podman inspect`) into shared logs.
- Updating a host secret file takes effect only after recreating the container during a planned maintenance window.
- Revoke compromised credentials at the provider before rotating the host-side secret file.
