"""Unit tests for scripts/kb_compound.py — Stage 7 compounding.

The contract worth defending: the script generates the SCAFFOLDING (log entry,
capability stub with provenance, index) and never the body. A stub whose body
is still unwritten is pending work, and the S7 gate blocks on it — otherwise
the knowledge base fills with empty pages and becomes the spec index it was
built to avoid.
"""

import shutil
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import kb_compound as kc
import workflow_gate as wg

WORKFLOW_YAML = REPO_ROOT / ".openspec" / "workflow.yaml"
CHANGE = "add-greeting"
DATE = "2026-08-28"


def make_repo(tmp_path, kb_enabled=True):
    root = tmp_path / "repo"
    (root / ".openspec").mkdir(parents=True, exist_ok=True)
    shutil.copy(WORKFLOW_YAML, root / ".openspec" / "workflow.yaml")
    # Set the flag explicitly in BOTH directions. Inheriting it from the
    # shipped config makes these tests fail in any repo that turned the
    # knowledge base on — which the destination is expected to do.
    path = root / ".openspec" / "workflow.yaml"
    cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
    cfg.setdefault("kb", {})["enabled"] = bool(kb_enabled)
    path.write_text(yaml.safe_dump(cfg, sort_keys=False))
    return root


def archive_change(root, name=CHANGE, date=DATE, caps=("greeting",), adr=True, signoffs=True):
    folder = root / "openspec" / "changes" / "archive" / f"{date}-{name}"
    (folder / "specs").mkdir(parents=True, exist_ok=True)
    for cap in caps:
        (folder / "specs" / cap).mkdir(parents=True, exist_ok=True)
        body = "# Delta\n\nADR-0001 governs this.\n" if adr else "# Delta\n"
        (folder / "specs" / cap / "spec.md").write_text(body)
    (folder / "proposal.md").write_text("# Why\n\nBecause.\n")
    (folder / "design.md").write_text("# Design\n\nPer ADR-0002.\n")
    cfg = {"schema": "spec-driven", "created": date}
    if signoffs:
        cfg["overrides"] = [
            {"key": "signoff.architecture", "after": "approved", "by": "nico", "when": date},
            {"key": "signoff.tasks", "after": "approved", "by": "nico", "when": date},
            {"key": "signoff.archive", "after": "approved", "by": "nico", "when": date},
        ]
    (folder / ".openspec.yaml").write_text(yaml.safe_dump(cfg, sort_keys=False))
    return folder


def run(root, *args):
    return kc.main([*args, "--repo", str(root)])


# ------------------------------------------------------------------ disabled

def test_no_op_when_kb_disabled(tmp_path, capsys):
    root = make_repo(tmp_path, kb_enabled=False)
    archive_change(root)
    assert run(root) == 0
    assert "nothing to compound" in capsys.readouterr().out
    assert not (root / "docs" / "log.md").exists()


def test_check_passes_when_kb_disabled(tmp_path):
    root = make_repo(tmp_path, kb_enabled=False)
    archive_change(root)
    assert run(root, "--check") == 0


# -------------------------------------------------------------------- writing

def test_writes_log_stub_and_index(tmp_path):
    root = make_repo(tmp_path)
    archive_change(root)
    assert run(root) == 0
    log = (root / "docs" / "log.md").read_text()
    assert f"### {CHANGE}" in log and DATE in log
    assert "ADR-0001" in log and "ADR-0002" in log
    assert "architecture (nico" in log
    stub = (root / "docs" / "capabilities" / "greeting.md").read_text()
    assert "type: Capability" in stub
    assert "openspec/specs/greeting/spec.md" in stub
    assert "kb_compound/1.0" in stub
    assert "authors: [human:nico]" in stub
    assert (root / "docs" / "index.md").is_file()


def test_stub_body_is_left_unwritten(tmp_path):
    """The script must never invent the why."""
    root = make_repo(tmp_path)
    archive_change(root)
    run(root)
    stub = (root / "docs" / "capabilities" / "greeting.md").read_text()
    assert kc.MARKER in stub
    assert "Because." not in stub          # the proposal's text is not copied
    assert "# Delta" not in stub           # neither is the spec's


def test_is_idempotent(tmp_path):
    root = make_repo(tmp_path)
    archive_change(root)
    run(root)
    first = (root / "docs" / "log.md").read_text()
    run(root)
    assert (root / "docs" / "log.md").read_text() == first
    assert first.count(f"### {CHANGE}") == 1


def test_existing_capability_page_is_never_overwritten(tmp_path):
    root = make_repo(tmp_path)
    archive_change(root)
    run(root)
    page = root / "docs" / "capabilities" / "greeting.md"
    page.write_text("---\ntype: Capability\ntitle: Greeting\n---\n\nHand-written truth.\n")
    run(root)
    assert "Hand-written truth." in page.read_text()


def test_multiple_capabilities(tmp_path):
    root = make_repo(tmp_path)
    archive_change(root, caps=("greeting", "reminders"))
    run(root)
    for cap in ("greeting", "reminders"):
        assert (root / "docs" / "capabilities" / f"{cap}.md").is_file()


def test_most_recent_change_is_the_default(tmp_path):
    root = make_repo(tmp_path)
    archive_change(root, name="old-one", date="2026-07-01", caps=("old",))
    archive_change(root, name="new-one", date="2026-08-20", caps=("new",))
    run(root)
    log = (root / "docs" / "log.md").read_text()
    assert "### new-one" in log and "### old-one" not in log


# --------------------------------------------------------------------- --check

def test_check_reports_missing_log_and_stub(tmp_path, capsys):
    root = make_repo(tmp_path)
    archive_change(root)
    assert run(root, "--check") == 1
    out = capsys.readouterr().out
    assert "no log entry" in out
    assert "missing capability page" in out


def test_check_blocks_on_unwritten_body(tmp_path, capsys):
    """The teeth: scaffolding alone is not compounding."""
    root = make_repo(tmp_path)
    archive_change(root)
    run(root)
    assert run(root, "--check") == 1
    assert "still unwritten" in capsys.readouterr().out


def test_check_passes_once_the_why_is_written(tmp_path, capsys):
    root = make_repo(tmp_path)
    archive_change(root)
    run(root)
    page = root / "docs" / "capabilities" / "greeting.md"
    page.write_text(page.read_text().replace(kc.STUB_BODY, "Greeting exists so onboarding has a smoke test.\n"))
    assert run(root, "--check") == 0
    assert "folded into the knowledge base" in capsys.readouterr().out


def test_no_archived_change_is_an_error(tmp_path, capsys):
    root = make_repo(tmp_path)
    (root / "openspec" / "changes" / "archive").mkdir(parents=True, exist_ok=True)
    assert run(root) == 1
    assert "COMPOUND ERROR" in capsys.readouterr().out


# ------------------------------------------------------------- gate wiring (S7)

def test_gate_s7_blocks_until_compounded(tmp_path):
    root = make_repo(tmp_path)
    archive_change(root)
    (root / "scripts").mkdir(parents=True, exist_ok=True)
    shutil.copy(SCRIPTS_DIR / "kb_compound.py", root / "scripts" / "kb_compound.py")
    shutil.copy(SCRIPTS_DIR / "workflow_gate.py", root / "scripts" / "workflow_gate.py")
    shutil.copy(SCRIPTS_DIR / "kb_validate.py", root / "scripts" / "kb_validate.py")
    cfg, _ = wg.load_workflow(root)
    ok, reasons = wg.run_kb_compound_check(root, cfg)
    assert not ok
    run(root)  # scaffold only — the why is still unwritten
    ok, _ = wg.run_kb_compound_check(root, cfg)
    assert not ok
    page = root / "docs" / "capabilities" / "greeting.md"
    page.write_text(page.read_text().replace(kc.STUB_BODY, "The why.\n"))
    ok, _ = wg.run_kb_compound_check(root, cfg)
    assert ok


def test_gate_s7_ignores_compound_when_kb_disabled(tmp_path):
    root = make_repo(tmp_path, kb_enabled=False)
    cfg, _ = wg.load_workflow(root)
    assert wg.run_kb_compound_check(root, cfg) == (True, "")


def test_check_passes_when_nothing_is_archived_yet(tmp_path, capsys):
    """A repo with the KB enabled whose first change has not reached archive.
    Nothing to compound is not pending work; blocking S7 here would punish a
    project for turning the knowledge base on early."""
    root = make_repo(tmp_path)
    (root / "openspec" / "changes" / "archive").mkdir(parents=True, exist_ok=True)
    assert run(root, "--check") == 0
    assert "nothing archived yet" in capsys.readouterr().out


def test_write_mode_still_reports_nothing_archived(tmp_path, capsys):
    root = make_repo(tmp_path)
    (root / "openspec" / "changes" / "archive").mkdir(parents=True, exist_ok=True)
    assert run(root) == 1
    assert "COMPOUND ERROR" in capsys.readouterr().out


def test_check_named_change_that_is_not_archived_still_errors(tmp_path, capsys):
    """--check --change <name> asks about a specific change; a typo must not
    pass silently."""
    root = make_repo(tmp_path)
    (root / "openspec" / "changes" / "archive").mkdir(parents=True, exist_ok=True)
    assert run(root, "--check", "--change", "nope") == 1
    assert "COMPOUND ERROR" in capsys.readouterr().out
