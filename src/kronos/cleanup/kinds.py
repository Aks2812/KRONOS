"""Idempotent teardown-callable factories for each artifact kind
`kronos.cleanup` tracks (SPEC_BRIEF6 §2). Every callable returned here
is a zero-arg `Callable[[], str | None]`, safe to call on an
already-gone target: it returns `"already_gone"` when there was
nothing left to do, `None` on an ordinary successful disposal, and
raises only on a genuine, unexpected failure (which `CleanupRegistry`
catches and records — see `registry.py`).

None of these call into `kronos.budget` — teardown is budget-exempt
(FORK-F's DEFAULT).
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Callable, Optional, Union

_ALREADY_GONE_MARKERS = (
    "no such container",
    "no such network",
    "no such volume",
    "no such object",
)


def _run_docker(args: list[str]) -> Optional[str]:
    result = subprocess.run(["docker", *args], capture_output=True, text=True)
    if result.returncode == 0:
        return None
    stderr = (result.stderr or "").lower()
    if any(marker in stderr for marker in _ALREADY_GONE_MARKERS):
        return "already_gone"
    raise RuntimeError(f"docker {' '.join(args)} failed: {result.stderr.strip()}")


def remove_container(name: str) -> Callable[[], Optional[str]]:
    """`docker rm -f <name>` — "no such container" counts as success."""
    return lambda: _run_docker(["rm", "-f", name])


def remove_network(name: str) -> Callable[[], Optional[str]]:
    """`docker network rm <name>` — "no such network" counts as success."""
    return lambda: _run_docker(["network", "rm", name])


def remove_volume(name: str) -> Callable[[], Optional[str]]:
    """`docker volume rm <name>` — "no such volume" counts as success."""
    return lambda: _run_docker(["volume", "rm", name])


def compose_down(compose_fn: Callable[..., None]) -> Callable[[], Optional[str]]:
    """Wrap an existing `compose(*args)` helper (e.g.
    `cybergym.selftest.compose`) as a single teardown callable for "the
    whole range stack." `docker compose down` is already a no-op on an
    already-down stack, so no extra already-gone detection is needed —
    a clean return always means `None` ("done"), never a failure."""

    def _teardown() -> Optional[str]:
        compose_fn("down", "-v")
        return None

    return _teardown


def remove_file(path: Union[str, Path]) -> Callable[[], Optional[str]]:
    def _teardown() -> Optional[str]:
        try:
            Path(path).unlink()
        except FileNotFoundError:
            return "already_gone"
        return None

    return _teardown


def remove_dir(path: Union[str, Path]) -> Callable[[], Optional[str]]:
    def _teardown() -> Optional[str]:
        import shutil

        p = Path(path)
        if not p.exists():
            return "already_gone"
        shutil.rmtree(p)
        return None

    return _teardown


def shred_credential_file(path: Union[str, Path]) -> Callable[[], Optional[str]]:
    """Overwrite a temp credential file with random bytes, then unlink
    it — removed from disk, not just logged (guardrail 6). Missing is
    success, not failure."""

    def _teardown() -> Optional[str]:
        p = Path(path)
        try:
            size = p.stat().st_size
        except FileNotFoundError:
            return "already_gone"
        with open(p, "wb") as fh:
            fh.write(os.urandom(size))
            fh.flush()
            os.fsync(fh.fileno())
        p.unlink()
        return None

    return _teardown


def terminate_process(proc) -> Callable[[], Optional[str]]:
    """Pre-wired for the agent layer (SPEC_BRIEF6 §2: nothing spawns
    long-lived background processes today, but the kind + teardown
    exist so that layer needs no new cleanup plumbing). Terminates a
    `subprocess.Popen`-like handle, tolerating one that already exited."""

    def _teardown() -> Optional[str]:
        if proc.poll() is not None:
            return "already_gone"
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
        return None

    return _teardown
