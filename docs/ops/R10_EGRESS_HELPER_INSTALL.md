# R10 least-privilege egress-guard helper — install / verify / rollback / uninstall

Human operator runbook. Everything here is a **privileged host action performed by a
human maintainer**, never by the loop. The loop never installs the helper, never edits
sudoers, and never mutates the firewall. These steps make the single authorized R10 run
able to apply the bounded `KRONOS-CYBERGYM-EGRESS` guard without running the whole
evaluation as root.

## What gets installed

1. `scripts/kronos-cybergym-egress` (repo source) → `/usr/local/sbin/kronos-cybergym-egress`, **root-owned**, mode `0755`.
2. `deploy/sudoers.d/kronos-cybergym-egress` (repo template, after editing `RUNUSER`) → `/etc/sudoers.d/kronos-cybergym-egress`, **root-owned**, mode `0440`.
3. `/etc/kronos-cybergym/egress.conf` (written by the operator) → **root-owned**, mode `0644`, directory `0755` root:root. It is the ONLY source of subnet/gateway/network.

The run user is never given write access to any installed path. The repo's writable
`scripts/kronos-cybergym-egress` is only the install **source**; sudoers whitelists only
the installed absolute path.

## Pinned config (run as root, before the helper is used)

Write the file from the signed `scope_manifest.yaml` / the lab Compose ipam. Exactly three keys:

```
install -d -o root -g root -m 0755 /etc/kronos-cybergym
cat > /etc/kronos-cybergym/egress.conf <<'EOF'
subnet=<private IPv4 CIDR from the signed manifest / compose ipam, e.g. 172.18.0.0/16>
gateway=<host address strictly inside subnet, not the network or broadcast address, e.g. 172.18.0.1>
network=<Docker network name pinned by the lab Compose, e.g. cybergym_default>
EOF
chown root:root /etc/kronos-cybergym/egress.conf
chmod 0644 /etc/kronos-cybergym/egress.conf
```

The helper also `lstat`s the file and refuses it unless it is a regular file (not a symlink),
owned by uid 0, with no group/other write bit. The in-process (root) executor path and the
non-root executor path additionally require the caller's subnet/gateway to equal these pinned values.

A missing, unreadable, untrusted or malformed config makes the helper fail closed (non-zero exit, no
iptables call).

## Install (run as root)

```
install -o root -g root -m 0755 scripts/kronos-cybergym-egress /usr/local/sbin/kronos-cybergym-egress

# edit RUNUSER -> the unprivileged account that runs the evaluation, into a TEMP copy;
# validate it BEFORE it can become active, and only then move it into /etc/sudoers.d:
tmp=$(mktemp)
cp deploy/sudoers.d/kronos-cybergym-egress "$tmp"
# (edit RUNUSER in "$tmp")
visudo -cf "$tmp" \
  && install -o root -g root -m 0440 "$tmp" /etc/sudoers.d/kronos-cybergym-egress \
  && visudo -cf /etc/sudoers.d/kronos-cybergym-egress        # must print: parsed OK
rm -f "$tmp"
```

A bad sudoers file never lands in `/etc/sudoers.d`: the `install` runs only if `visudo -cf` of the
temp copy succeeded.

## Verify (as the run user, non-interactive)

```
sudo -n /usr/local/sbin/kronos-cybergym-egress status   # prints: absent   (before any run)
```

A non-zero exit or a password prompt means the policy is not in force — STOP and fix the
install before authorizing the run. The helper takes no arguments and rejects anything
outside its contract:

```
sudo -n /usr/local/sbin/kronos-cybergym-egress bogus     # rc 1, no firewall change
sudo -n /usr/local/sbin/kronos-cybergym-egress apply 1.1.1.1   # denied by sudoers (no wildcard); the helper also rejects any argument
```

## Rollback (remove the guard; leaves helper + sudoers in place)

Run only AFTER Compose teardown. The verbs take no arguments; the subnet comes from the
pinned config:

```
sudo -n /usr/local/sbin/kronos-cybergym-egress remove    # prints: removed / already_gone
sudo -n /usr/local/sbin/kronos-cybergym-egress status    # prints: absent
```

`remove` first runs a read-only `docker network inspect <pinned network> --format '{{len .Containers}}'`
(absolute docker path, never `PATH`; it creates nothing). It proceeds only if the network is gone
or has 0 attached containers. With >=1 attached container, docker absent, an inspect error or
unparseable output it REFUSES (non-zero, no firewall change). `status` reports `absent` only on a
positive iptables rc 1; rc 2 or any other non-zero is an error, never `absent`. `remove` never
claims `removed`/`already_gone` on rc 2. It never touches `DOCKER-USER`, `INPUT` or any foreign
chain beyond deleting its own scoped jumps.

Manual root override (only for the misconfigured-host edge where docker is absent and `remove`
refuses): confirm the lab is down, then as root delete exactly the recorded guard for the pinned
subnet:

```
iptables -w -D DOCKER-USER -s <subnet> -j KRONOS-CYBERGYM-EGRESS
iptables -w -D INPUT -s <subnet> -j KRONOS-CYBERGYM-EGRESS
iptables -w -F KRONOS-CYBERGYM-EGRESS
iptables -w -X KRONOS-CYBERGYM-EGRESS
```

## Uninstall (remove helper + policy entirely, as root)

Remove the helper only after `remove` succeeded AND `status` confirms `absent`; otherwise STOP
(use the manual override above if needed, then re-check `status`). The `rm` commands are chained
with `&&` so a failed `remove`, or a `status` other than exactly `absent`, never leads to `rm`:

```
/usr/local/sbin/kronos-cybergym-egress remove \
  && [ "$(/usr/local/sbin/kronos-cybergym-egress status)" = "absent" ] \
  && rm -f /usr/local/sbin/kronos-cybergym-egress /etc/sudoers.d/kronos-cybergym-egress /etc/kronos-cybergym/egress.conf
```

## Notes

- The helper is self-contained (stdlib only) and does not import the repo package, so a
  modified working tree cannot change what runs as root.
- `apply` / `remove` / `status` are the only accepted verbs and take NO arguments; subnet,
  gateway and network come only from the pinned config. The subnet must be a private,
  non-public IPv4 lab subnet (`ipaddress.is_private`; a Docker RFC1918 bridge range satisfies
  this), the gateway a host IPv4 strictly inside it (not the network or broadcast address), and
  `0.0.0.0/0` or any public-routable range is rejected fail-closed. Everything else is rejected too.
- Absolute binaries only: the helper pins its interpreter (`#!/usr/bin/python3`), resolves
  `iptables` from `/usr/sbin/iptables` or `/sbin/iptables`, and `docker` from `/usr/bin/docker`
  or `/usr/local/bin/docker` (never via `PATH`); the executor invokes `/usr/bin/sudo` (or
  `/bin/sudo`) by absolute path. Keep sudo's `secure_path` set (the distro default) so the
  root-side `sudo -n <helper>` resolves nothing from the caller's `PATH`.
