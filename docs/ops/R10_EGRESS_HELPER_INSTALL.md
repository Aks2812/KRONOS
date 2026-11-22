# R10 least-privilege egress-guard helper — install / verify / rollback / uninstall

Human operator runbook. Everything here is a **privileged host action performed by a
human maintainer**, never by the loop. The loop never installs the helper, never edits
sudoers, and never mutates the firewall. These steps make the single authorized R10 run
able to apply the bounded `KRONOS-CYBERGYM-EGRESS` guard without running the whole
evaluation as root.

## What gets installed

1. `scripts/kronos-cybergym-egress` (repo source) → `/usr/local/sbin/kronos-cybergym-egress`, **root-owned**, mode `0755`.
2. `deploy/sudoers.d/kronos-cybergym-egress` (repo template, after editing `RUNUSER`) → `/etc/sudoers.d/kronos-cybergym-egress`, **root-owned**, mode `0440`.

The run user is never given write access to either installed path. The repo's writable
`scripts/kronos-cybergym-egress` is only the install **source**; sudoers whitelists only
the installed absolute path.

## Install (run as root)

```
install -o root -g root -m 0755 scripts/kronos-cybergym-egress /usr/local/sbin/kronos-cybergym-egress

# edit RUNUSER -> the unprivileged account that runs the evaluation, then:
install -o root -g root -m 0440 deploy/sudoers.d/kronos-cybergym-egress /etc/sudoers.d/kronos-cybergym-egress
visudo -cf /etc/sudoers.d/kronos-cybergym-egress        # must print: parsed OK
```

## Verify (as the run user, non-interactive)

```
sudo -n /usr/local/sbin/kronos-cybergym-egress status   # prints: absent   (before any run)
```

A non-zero exit or a password prompt means the policy is not in force — STOP and fix the
install before authorizing the run. The helper also rejects anything outside its contract:

```
sudo -n /usr/local/sbin/kronos-cybergym-egress bogus     # rc 1, no firewall change
sudo -n /usr/local/sbin/kronos-cybergym-egress apply --flush 1.1.1.1   # rc 1, rejected
```

## Rollback (remove the guard; leaves helper + sudoers in place)

If a run leaves the chain applied, remove it with the same bounded verb (subnet is the
value Docker assigned to the lab network, e.g. `172.18.0.0/16`):

```
sudo -n /usr/local/sbin/kronos-cybergym-egress remove <subnet>   # prints: removed / already_gone
sudo -n /usr/local/sbin/kronos-cybergym-egress status            # prints: absent
```

The remove verb is idempotent and never touches `DOCKER-USER`, `INPUT`, or any foreign
chain.

## Uninstall (remove helper + policy entirely, as root)

```
sudo -n /usr/local/sbin/kronos-cybergym-egress remove <subnet>   # if still applied
rm -f /usr/local/sbin/kronos-cybergym-egress
rm -f /etc/sudoers.d/kronos-cybergym-egress
```

## Notes

- The helper is self-contained (stdlib only) and does not import the repo package, so a
  modified working tree cannot change what runs as root.
- `apply` / `remove` / `status` are the only accepted verbs; `apply <subnet> <gateway>`,
  `remove <subnet>`, `status` are the only accepted argument shapes; the subnet must be a
  private, non-public IPv4 lab subnet (`ipaddress.is_private`; a Docker RFC1918 bridge range
  satisfies this), the gateway a valid IPv4 inside it, and `0.0.0.0/0` or any public-routable
  range is rejected fail-closed. Everything else is rejected too.
- Absolute binaries only: the helper pins its interpreter (`#!/usr/bin/python3`) and resolves
  `iptables` from `/usr/sbin/iptables` or `/sbin/iptables` (never via `PATH`); the executor
  invokes `/usr/bin/sudo` (or `/bin/sudo`) by absolute path. Keep sudo's `secure_path` set
  (the distro default) so the root-side `sudo -n <helper>` resolves nothing from the caller's
  `PATH`.
