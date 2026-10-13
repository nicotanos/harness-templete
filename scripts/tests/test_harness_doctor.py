"""Unit tests for scripts/harness_doctor.py.

The contract: `todo` means the harness does not work here and the exit code
says so; `yours` means a decision nobody has made, which must never fail the
command. Conflating the two is how a setup report turns into noise people learn
to ignore.
"""

import json
import shutil
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import harness_doctor as hd

WORKFLOW_YAML = REPO_ROOT / ".openspec" / "workflow.yaml"


def make_repo(tmp_path, *, adrs=("ADR-0001-artifact-enforced-pipeline.md",),
              readme="# my project\n\nDoes a thing.\n", gitignore=".pipeline/\n",
              settings=True, license_=True):
    root = tmp_path / "repo"
    (root / ".openspec").mkdir(parents=True, exist_ok=True)
    (root / "scripts").mkdir(parents=True, exist_ok=True)
    shutil.copy(WORKFLOW_YAML, root / ".openspec" / "workflow.yaml")
    for name in ("workflow_gate.py", "kb_validate.py"):
        shutil.copy(SCRIPTS_DIR / name, root / "scripts" / name)
    (root / "docs" / "adr").mkdir(parents=True, exist_ok=True)
    for adr in adrs:
        (root / "docs" / "adr" / adr).write_text("---\ntype: ADR\ntitle: t\ncreated_ts: 2026-01-01T00:00:00Z\nauthors: [human:x]\n---\n\n# t\n")
    if readme is not None:
        (root / "README.md").write_text(readme)
    if gitignore is not None:
        (root / ".gitignore").write_text(gitignore)
    if settings:
        (root / ".claude").mkdir(parents=True, exist_ok=True)
        (root / ".claude" / "settings.json").write_text(json.dumps(
            {"hooks": {"Stop": [{"hooks": []}], "PreToolUse": [{"hooks": []}]}}))
    if license_:
        (root / "LICENSE").write_text("MIT\n")
    return root


@pytest.fixture(autouse=True)
def no_external_tools(monkeypatch):
    """Keep these tests hermetic. The openspec CLI and the gate have their own
    suites; what is under test here is how findings are classified."""
    monkeypatch.setattr(hd, "check_openspec", lambda r, root: r.add(hd.OK, "openspec CLI", "v1.11.0"))
    monkeypatch.setattr(hd, "check_opsx_commands", lambda r, root: r.add(hd.OK, "/opsx: commands", "12 generated"))
    monkeypatch.setattr(hd, "check_gate", lambda r, root: r.add(hd.OK, "gate", "GATE idle"))


def run(root, capsys):
    rc = hd.main(["--repo", str(root)])
    return rc, capsys.readouterr().out


def kinds(out):
    """{title: kind} parsed from the rendered report."""
    found = {}
    for line in out.splitlines():
        if line.startswith("["):
            mark, rest = line[1:].split("]", 1)
            found[rest.strip().split("  ")[0].strip()] = mark.strip() or "ok"
    return found


# ------------------------------------------------------- todo vs yours

def test_open_decisions_do_not_fail_the_command(tmp_path, capsys):
    """Everything working, several decisions open: exit 0."""
    root = make_repo(tmp_path)
    rc, out = run(root, capsys)
    assert rc == 0
    assert "yours" in out
    assert "decision(s) still open" in out


def test_a_todo_fails_the_command(tmp_path, capsys):
    root = make_repo(tmp_path, gitignore="node_modules/\n")  # .pipeline/ not ignored
    rc, out = run(root, capsys)
    assert rc == 1
    assert "to fix before the harness works" in out


# ------------------------------------------------------------- the checks

def test_template_readme_is_flagged_as_yours(tmp_path, capsys):
    root = make_repo(tmp_path, readme="# SDD Harness\n\nA template repo for artifact-enforced ...\n")
    _rc, out = run(root, capsys)
    assert kinds(out)["README"] == "yours"
    assert "still describes the harness" in out


def test_project_readme_is_ok(tmp_path, capsys):
    root = make_repo(tmp_path)
    _rc, out = run(root, capsys)
    assert kinds(out)["README"] == "ok"


def test_only_the_seed_adr_is_an_open_decision(tmp_path, capsys):
    root = make_repo(tmp_path)
    assert kinds(run(root, capsys)[1])["ADRs"] == "yours"


def test_own_adrs_are_ok(tmp_path, capsys):
    root = make_repo(tmp_path, adrs=("ADR-0001-artifact-enforced-pipeline.md", "ADR-0002-postgres.md"))
    assert kinds(run(root, capsys)[1])["ADRs"] == "ok"


def test_no_adr_at_all_is_a_todo(tmp_path, capsys):
    """Stage 2 blocks on an empty ADR directory, so this is not optional."""
    root = make_repo(tmp_path, adrs=())
    _rc, out = run(root, capsys)
    assert kinds(out)["ADRs"] == "TODO"


def test_unignored_pipeline_dir_is_a_todo(tmp_path, capsys):
    root = make_repo(tmp_path, gitignore="*.pyc\n")
    assert kinds(run(root, capsys)[1])["transient reports ignored"] == "TODO"


def test_missing_settings_is_a_todo(tmp_path, capsys):
    """No hooks means nothing enforces the gate — that is not a preference."""
    root = make_repo(tmp_path, settings=False)
    _rc, out = run(root, capsys)
    assert kinds(out)["Claude Code hooks"] == "TODO"
    assert "not enforced" in out


def test_missing_license_is_yours(tmp_path, capsys):
    root = make_repo(tmp_path, license_=False)
    assert kinds(run(root, capsys)[1])["LICENSE"] == "yours"


def test_kb_disabled_is_an_open_decision(tmp_path, capsys):
    root = make_repo(tmp_path)
    assert kinds(run(root, capsys)[1])["knowledge base"] == "yours"


def test_kb_enabled_but_invalid_is_a_todo(tmp_path, capsys):
    root = make_repo(tmp_path)
    path = root / ".openspec" / "workflow.yaml"
    cfg = yaml.safe_load(path.read_text())
    cfg["kb"]["enabled"] = True
    path.write_text(yaml.safe_dump(cfg, sort_keys=False))
    (root / "docs" / "broken.md").write_text("no frontmatter\n")
    _rc, out = run(root, capsys)
    assert kinds(out)["knowledge base"] == "TODO"


def test_broken_workflow_config_stops_early(tmp_path, capsys):
    root = make_repo(tmp_path)
    (root / ".openspec" / "workflow.yaml").write_text("stage_index: not-a-mapping\n")
    rc, out = run(root, capsys)
    assert rc == 1
    assert "workflow config" in out
