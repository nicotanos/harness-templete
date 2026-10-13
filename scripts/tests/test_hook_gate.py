"""Unit tests for scripts/hook_gate.py (deterministic PreToolUse gate trigger).

Claude Code's `if: "Bash(...)"` filter fails open on commands containing
$()/backtick/$VAR expansions, so the hook handler must re-check the actual
command from stdin before running the workflow gate. Plain pytest, same
style as scripts/tests/.
"""

import io
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import hook_gate as hg


def stdin_payload(command):
    return json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})


def fake_gate(root, exit_code, label="GATE S3 tasks BLOCKED: upstream"):
    (root / "scripts").mkdir(parents=True, exist_ok=True)
    (root / "scripts" / "workflow_gate.py").write_text(
        f"#!/usr/bin/env python3\nimport sys\nprint({label!r})\nsys.exit({exit_code})\n"
    )


# ---------------------------------------------------------------- matching

@pytest.mark.parametrize("command", [
    "openspec instructions apply --change identity-access-model",
    "python3 -m openspec instructions apply --change x",
    "python -m openspec instructions apply --change x",
    "npx openspec instructions apply --change x",
    "FOO=bar python3 -m openspec instructions apply --change x",
    "echo hi && openspec instructions apply --change x",
    "openspec instructions apply",
])
def test_s3_matches(command):
    assert hg.command_matches(command, "S3")


@pytest.mark.parametrize("command", [
    "python3 scripts/workflow_gate.py --change identity-access-model 2>&1; echo \"exit=$?\"",
    "ls -la $(pwd)",
    "git status --short",
    "openspec instructions proposal --change x",
    "openspec instructions applyx --change x",
    "echo 'openspec instructions apply' in docs",
    "openspec validate --all",
])
def test_s3_does_not_match(command):
    assert not hg.command_matches(command, "S3")


@pytest.mark.parametrize("stage,command", [
    ("S0", "openspec new change fix-claim-status-transition"),
    ("S0", "openspec instructions proposal --change x"),
    ("S0", "openspec instructions specs --change x"),
    ("S1", "openspec instructions design --change x"),
    ("S2", "openspec instructions tasks --change x"),
    ("S5", "openspec validate --specs --change x"),
    ("S6", "openspec archive fix-claim-status-transition"),
    ("S6", "openspec.cmd archive fix-claim-status-transition"),
])
def test_stage_matches(stage, command):
    assert hg.command_matches(command, stage)


# ---------------------------------------------------------------- main()

def test_main_nonmatching_exits_zero(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    fake_gate(root, 7)  # would block if invoked — must not be
    monkeypatch.setattr(sys, "stdin", io.StringIO(stdin_payload("git status --short")))
    assert hg.main(["--stage", "S3", "--repo", str(root)]) == 0


def test_main_matching_runs_gate_and_propagates(tmp_path, monkeypatch, capsys):
    root = tmp_path / "repo"
    fake_gate(root, 1, label="GATE S3 tasks BLOCKED: upstream")
    monkeypatch.setattr(sys, "stdin", io.StringIO(stdin_payload("openspec instructions apply --change x")))
    assert hg.main(["--stage", "S3", "--repo", str(root)]) == 1
    assert "GATE S3 tasks BLOCKED" in capsys.readouterr().out


def test_main_fail_open_command_still_noops(tmp_path, monkeypatch):
    """The reported bug: a probe with $? / 2>&1 / ';' must NOT gate."""
    root = tmp_path / "repo"
    fake_gate(root, 1)  # would block if invoked — must not be
    cmd = 'python3 scripts/workflow_gate.py --change identity-access-model 2>&1; echo "exit=$?"'
    monkeypatch.setattr(sys, "stdin", io.StringIO(stdin_payload(cmd)))
    assert hg.main(["--stage", "S3", "--repo", str(root)]) == 0


def test_main_unparseable_stdin_runs_gate(tmp_path, monkeypatch, capsys):
    """Cannot verify the command — preserve enforcement (run the gate)."""
    root = tmp_path / "repo"
    fake_gate(root, 3, label="GATE S3 tasks BLOCKED: upstream")
    monkeypatch.setattr(sys, "stdin", io.StringIO("not json"))
    assert hg.main(["--stage", "S3", "--repo", str(root)]) == 3
    assert "GATE S3 tasks BLOCKED" in capsys.readouterr().out
