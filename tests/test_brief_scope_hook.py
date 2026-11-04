"""Black-box tests for .claude/hooks/brief-scope.sh gh-api method filter (no network)."""
import json
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOK = REPO_ROOT / ".claude" / "hooks" / "brief-scope.sh"
EP = "repos/Aks2812/KRONOS/pulls/5"


def run_hook(command: str) -> dict | None:
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})
    r = subprocess.run(
        ["bash", str(HOOK)], input=payload, capture_output=True, text=True, timeout=30
    )
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout) if r.stdout.strip() else None


def decision(command: str) -> str | None:
    out = run_hook(command)
    return out["hookSpecificOutput"]["permissionDecision"] if out else None


DENY_CASES = [
    f"gh api {EP} -f draft=false",
    f"gh api {EP} -F a=b",
    f"gh api {EP} --field x=y",
    f"gh api {EP} --raw-field c=d",
    f"gh api {EP} --input body.json",
    f"gh api {EP} --input=body.json",
    f"gh api {EP} -ffoo=bar",
    f"gh api {EP} -XPOST",
    f"gh api {EP} -X POST",
    f"gh api {EP} --method POST",
    f"gh api {EP} --method=PATCH",
    f"gh api {EP} -XDELETE",
    f"gh api {EP} -X PUT",
    f"gh api {EP} --method DELETE",
    f"gh api {EP} --method GET -f a=b",
    f"x=$(gh api {EP} -f a=b)",
    f"echo `gh api {EP} -XPOST`",
    f"git status && gh api {EP} -X POST",
    f"sh -c 'gh api {EP} -X POST'",
    f"gh api {EP} --method $M",
    f"gh api {EP} --bogus",
    f"gh api {EP} -X 'POST",
    # argv0 forms
    f"/usr/bin/gh api {EP} -f draft=false",
    f"./gh api {EP} -f a=b",
    f"G=gh; $G api {EP} -f a=b",
    f"${{G}} api {EP} -f a=b",
    f"NAME=1 gh api {EP} -f a=b",
    f"env gh api {EP} -f a=b",
    f"command gh api {EP} -f a=b",
    f"env X=1 /usr/bin/gh api {EP} -XPOST",
    f"$G api {EP}",
    f"$(echo gh) api {EP} -f a=b",
    f"`echo gh` api {EP} -f a=b",
    f"env $G api {EP}",
    f"alias g=gh; g api {EP} -f a=b",
]

ALLOW_CASES = [
    f"gh api {EP}",
    "gh api repos/Aks2812/KRONOS/issues/3 --method GET",
    f"gh api {EP} -X GET",
    f"gh api {EP} -H 'Accept: application/json' --jq '.title'",
    "git status",
    # argv0 forms
    f"/usr/bin/gh api {EP}",
    f"gh api {EP} --method GET",
    "env FOO=1 ls",
]


@pytest.mark.parametrize("cmd", DENY_CASES)
def test_mutating_gh_api_denied(cmd):
    assert decision(cmd) == "deny"


@pytest.mark.parametrize("cmd", ALLOW_CASES)
def test_read_or_non_gh_not_denied(cmd):
    assert decision(cmd) != "deny"
