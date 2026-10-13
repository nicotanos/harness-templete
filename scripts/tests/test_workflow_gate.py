"""Unit tests for scripts/workflow_gate.py (the SDD pipeline L1 gate).

Plain pytest, mirroring the style of scripts/tests/: module imported via
sys.path from the scripts directory; the real .openspec/workflow.yaml is
copied into each tmp repo so the tests lock the shipped config contract.
The openspec CLI, kb_validate and openspec validate are faked at the module
IO seams (query_status / list_changes / run_kb_validate /
run_openspec_validate); end-to-end runs against the real CLI are performed
manually (see the piece build notes).
"""

import shutil
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import workflow_gate as wg

WORKFLOW_YAML = REPO_ROOT / ".openspec" / "workflow.yaml"
CHANGE = "feat-x"
PLANNING_DONE = {"proposal": "done", "specs": "done", "design": "done"}


# ------------------------------------------------------------------ helpers

def layout(root):
    """The shipped config's `paths:` block, resolved for a tmp repo. Tests read
    the layout instead of assuming it, so a destination that customises
    `paths:` can still run this suite as its install check."""
    cfg = yaml.safe_load((root / ".openspec" / "workflow.yaml").read_text(encoding="utf-8"))
    paths = dict(wg.DEFAULT_PATHS)
    paths.update({k: v for k, v in (cfg.get("paths") or {}).items() if k in paths})
    return paths


def set_config(root, **blocks):
    """Merge top-level blocks into the tmp repo's workflow.yaml."""
    path = root / ".openspec" / "workflow.yaml"
    cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
    for key, value in blocks.items():
        if isinstance(value, dict) and isinstance(cfg.get(key), dict):
            cfg[key] = {**cfg[key], **value}
        else:
            cfg[key] = value
    path.write_text(yaml.safe_dump(cfg, sort_keys=False))


def gap_report_path(root):
    paths = layout(root)
    return Path(paths["pipeline_dir"]) / paths["gap_report"]


def verify_report_path(root):
    paths = layout(root)
    return Path(paths["pipeline_dir"]) / paths["verification_report"]


def make_root(tmp_path, gap_report=True):
    root = tmp_path / "repo"
    (root / ".openspec").mkdir(parents=True, exist_ok=True)
    shutil.copy(WORKFLOW_YAML, root / ".openspec" / "workflow.yaml")
    paths = layout(root)
    (root / paths["adr_dir"]).mkdir(parents=True, exist_ok=True)
    (root / paths["pipeline_dir"]).mkdir(parents=True, exist_ok=True)
    if gap_report:
        (root / paths["pipeline_dir"] / paths["gap_report"]).write_text(
            "# Gap report\n\nKnown: probe. Missing: nothing.\n"
        )
    return root


def write_change(root, name=CHANGE, stages=None, coding_flow=None, overrides=None):
    change_dir = root / layout(root)["changes_dir"] / name
    change_dir.mkdir(parents=True, exist_ok=True)
    cfg = {"schema": "spec-driven", "created": "2026-08-13"}
    if stages is not None:
        cfg["stages"] = stages
    if coding_flow is not None:
        cfg["coding_flow"] = coding_flow
    if overrides is not None:
        cfg["overrides"] = overrides
    (change_dir / ".openspec.yaml").write_text(yaml.safe_dump(cfg, sort_keys=False))
    return change_dir


def write_archived_change(root, name=CHANGE, date="2026-08-14", overrides=None):
    """A change whose records live under
    openspec/changes/archive/<date>-<name>/ (no active copy)."""
    change_dir = root / layout(root)["changes_dir"] / "archive" / f"{date}-{name}"
    change_dir.mkdir(parents=True, exist_ok=True)
    cfg = {"schema": "spec-driven", "created": date}
    if overrides is not None:
        cfg["overrides"] = overrides
    (change_dir / ".openspec.yaml").write_text(yaml.safe_dump(cfg, sort_keys=False))
    return change_dir


def fake_status(artifact_states, is_complete=True):
    return {
        "changeName": CHANGE,
        "artifacts": [
            {"id": k, "status": v, "requires": []} for k, v in artifact_states.items()
        ],
        "isPlanningComplete": is_complete,
        "isComplete": is_complete,
    }


def fake_progress(total, complete):
    """`openspec instructions apply --json`'s progress block."""
    return {"total": total, "complete": complete, "remaining": total - complete}


def signoff(stage, verdict="approved", by="user"):
    return {"key": f"signoff.{stage}", "after": verdict, "by": by, "when": "2026-08-13"}


def revision(stage, after="READY"):
    return {"key": f"revision.{stage}", "after": after, "by": "agent", "when": "2026-08-14"}


# Sign-off records that make stages S1..S<n> DONE under the default policy.
# S1 (domain-spec) has review: none — no sign-off record is needed (its review
# is absorbed into the combined S1+S2 review at S2, signoff.architecture).
SIGNOFFS_UP_TO = {
    "S1": [],
    "S2": [signoff("architecture")],
    "S3": [signoff("architecture"), signoff("tasks")],
    "S4": [signoff("architecture"), signoff("tasks")],
    "S5": [signoff("architecture"), signoff("tasks")],
    "S6": [signoff("architecture"), signoff("tasks"), signoff("archive")],
}


def seed_artifacts(root, change=CHANGE, adr_ref=True, anchored=True, report_passes=True):
    """S2/S3/S5 artifacts on disk (delta spec + ADR, tasks.md anchors,
    verification report)."""
    paths = layout(root)
    change_dir = root / paths["changes_dir"] / change
    (change_dir / "specs").mkdir(parents=True, exist_ok=True)
    spec = "# Probe\n\n## ADDED Requirements\n\nADR: 0001\n" if adr_ref else "# Probe\n\n## ADDED Requirements\n\nNo architecture.\n"
    (change_dir / "specs" / "probe.md").write_text(spec)
    if anchored:
        tasks = ("- [x] probe task\n"
                 "  - Domain: probe context\n"
                 "  - Event contract: ProbeCompleted (schema v1)\n"
                 "  - Rule: PROBE-R1\n"
                 "  - ADR: 0001\n"
                 "  - Infra: probe runtime\n"
                 "  - Tests: scripts/tests/test_workflow_gate.py\n")
    else:
        tasks = "- [x] probe task\n"
    (change_dir / "tasks.md").write_text(tasks)
    adrs = root / paths["adr_dir"]
    adrs.mkdir(parents=True, exist_ok=True)
    (adrs / "0001-probe.md").write_text("# ADR 0001: probe\n")
    report = "- PASS probe works\n" if report_passes else "- FAIL probe broken\n"
    (root / paths["pipeline_dir"] / paths["verification_report"]).write_text(report)


@pytest.fixture
def fakes(monkeypatch):
    """Default fakes: one change, all planning done, KB and validate pass."""
    monkeypatch.setattr(wg, "list_changes", lambda root: [CHANGE])
    monkeypatch.setattr(wg, "query_status", lambda root, change: fake_status(PLANNING_DONE))
    monkeypatch.setattr(wg, "query_task_progress", lambda root, change: fake_progress(3, 3))
    monkeypatch.setattr(wg, "run_kb_validate", lambda root, cfg=None: (True, ""))
    monkeypatch.setattr(wg, "run_openspec_validate", lambda root, change: (True, ""))


def run_gate(root, *args, capsys):
    rc = wg.main(["--repo", str(root), *args])
    return rc, capsys.readouterr().out


# ------------------------------------------------------------ config contract

def test_record_fields_match_workflow_config():
    cfg = yaml.safe_load(WORKFLOW_YAML.read_text(encoding="utf-8"))
    assert cfg["overrides"]["record"]["fields"] == wg.RECORD_FIELDS


def test_missing_workflow_config_is_error(tmp_path, capsys):
    root = tmp_path / "repo"
    root.mkdir()
    rc, out = run_gate(root, capsys=capsys)
    assert rc == 1
    assert "GATE ERROR" in out
    assert "workflow.yaml" in out


def test_unknown_stage_is_error(tmp_path, fakes, capsys):
    root = make_root(tmp_path)
    write_change(root)
    rc, out = run_gate(root, "--stage", "S9", capsys=capsys)
    assert rc == 1
    assert "GATE ERROR" in out
    assert "unknown stage" in out


def test_invalid_change_name_rejected(tmp_path, capsys):
    root = make_root(tmp_path)
    rc, out = run_gate(root, "--change", "../evil", "--stage", "S1", capsys=capsys)
    assert rc == 1
    assert "invalid change name" in out


# ------------------------------------------------------------ S0 intake

def test_s0_gap_report_missing_blocks(tmp_path, fakes, capsys):
    root = make_root(tmp_path, gap_report=False)
    rc, out = run_gate(root, "--stage", "S0", capsys=capsys)
    assert rc == 1
    assert "GATE S0 intake BLOCKED" in out
    assert "gap report" in out


def test_s0_gap_report_present_proceeds(tmp_path, fakes, capsys):
    root = make_root(tmp_path)
    rc, out = run_gate(root, "--stage", "S0", capsys=capsys)
    assert rc == 0
    assert "GATE S0 intake DONE" in out


def test_s0_no_workflow_missing_gap_report_blocks(tmp_path, fakes, capsys):
    """S0 intake is a PRE-WORKFLOW admission gate: even with no active or
    archived change, --stage S0 must enforce the gap report (the L1 hook runs
    it on `openspec new change` before a change exists)."""
    root = make_root(tmp_path, gap_report=False)
    wg.list_changes = lambda root: []  # noqa: E731 — no workflow in progress
    rc, out = run_gate(root, "--stage", "S0", capsys=capsys)
    assert rc == 1
    assert "GATE S0 intake BLOCKED" in out
    assert "gap report" in out


def test_s0_explicit_new_admission_ignores_archived_change(tmp_path, fakes, capsys):
    """An archived change must not satisfy a fresh explicit S0 admission;
    archive cleanup leaves no gap report, so the new workflow is blocked."""
    root = make_root(tmp_path, gap_report=False)
    write_archived_change(root, overrides=SIGNOFFS_UP_TO["S6"])
    wg.list_changes = lambda root: []  # noqa: E731 — no active change
    rc, out = run_gate(root, "--stage", "S0", capsys=capsys)
    assert rc == 1
    assert "GATE S0 intake BLOCKED" in out
    assert "gap report" in out

def test_s0_explicit_archived_change_requires_fresh_gap_report(tmp_path, fakes, capsys):
    """Explicit S0 admission must not inherit completion from an archive."""
    root = make_root(tmp_path, gap_report=False)
    write_archived_change(root, overrides=SIGNOFFS_UP_TO["S6"])
    wg.list_changes = lambda root: []  # noqa: E731 — no active change
    rc, out = run_gate(root, "--stage", "S0", "--change", CHANGE, capsys=capsys)
    assert rc == 1
    assert "GATE S0 intake BLOCKED" in out
    assert "gap report" in out

def test_s0_explicit_archived_malformed_config_reports_gap(tmp_path, fakes, capsys):
    """S0 admission must inspect only the fresh gap report, not archived metadata."""
    root = make_root(tmp_path, gap_report=False)
    archived = write_archived_change(root, overrides=SIGNOFFS_UP_TO["S6"])
    (archived / ".openspec.yaml").write_text("stages: [\n", encoding="utf-8")
    wg.list_changes = lambda root: []  # noqa: E731 — no active workflow
    rc, out = run_gate(root, "--stage", "S0", "--change", CHANGE, capsys=capsys)
    assert rc == 1
    assert "GATE S0 intake BLOCKED" in out
    assert "gap report" in out
    assert "YAML" not in out


def test_s0_no_workflow_gap_report_done(tmp_path, fakes, capsys):
    """--stage S0 with a gap report but no workflow → DONE (exit 0): intake
    evaluates its artifact even though no change exists yet."""
    root = make_root(tmp_path)
    wg.list_changes = lambda root: []  # noqa: E731 — no workflow in progress
    rc, out = run_gate(root, "--stage", "S0", capsys=capsys)
    assert rc == 0
    assert "GATE S0 intake DONE" in out


def test_s0_no_workflow_explicit_does_not_resolve_changes(tmp_path, monkeypatch, capsys):
    """Explicit pre-workflow S0 checks only the current gap report."""
    root = make_root(tmp_path)

    def fail_list_changes(_root):
        raise AssertionError("explicit S0 must not resolve active changes")

    monkeypatch.setattr(wg, "list_changes", fail_list_changes)
    rc, out = run_gate(root, "--stage", "S0", capsys=capsys)
    assert rc == 0
    assert "GATE S0 intake DONE" in out

    (root / gap_report_path(root)).unlink()
    rc, out = run_gate(root, "--stage", "S0", capsys=capsys)
    assert rc == 1
    assert "GATE S0 intake BLOCKED" in out
    assert "gap report" in out


def test_untouched_tree_is_idle_not_blocked(tmp_path, fakes, capsys):
    """No change and no gap report is a repo where nobody has started work,
    not a failure. The bare run answers "what's next" and must exit 0, or CI
    is red on every repo that is simply not mid-change.

    S0 admission is NOT weakened: it is enforced on the explicit `--stage S0`
    path, which is what the PreToolUse hooks call before `openspec new change`
    (see test_s0_explicit_still_blocks_on_an_untouched_tree)."""
    root = make_root(tmp_path, gap_report=False)
    wg.list_changes = lambda root: []  # noqa: E731 — no workflow in progress
    rc, out = run_gate(root, capsys=capsys)
    assert rc == 0
    assert "GATE idle" in out
    assert "Stage 0 starts a change" in out


def test_s0_explicit_still_blocks_on_an_untouched_tree(tmp_path, fakes, capsys):
    """The admission gate the hooks actually call. This is what blocks
    `openspec new change` until a gap report exists."""
    root = make_root(tmp_path, gap_report=False)
    wg.list_changes = lambda root: []  # noqa: E731
    rc, out = run_gate(root, "--stage", "S0", capsys=capsys)
    assert rc == 1
    assert "GATE S0 intake BLOCKED" in out
    assert "gap report" in out


def test_gap_report_without_a_change_is_the_normal_s0_state(tmp_path, fakes, capsys):
    """A gap report and no change yet is exactly where S0 leaves you: the
    report is written BEFORE `openspec new change`. Reporting it as stale
    would block the very turn that produced it (the Stop hook runs the bare
    gate), so idle reports S0 DONE and exits 0."""
    root = make_root(tmp_path)  # gap report present
    wg.list_changes = lambda root: []  # noqa: E731 — no workflow in progress
    rc, out = run_gate(root, capsys=capsys)
    assert rc == 0
    assert "S0 intake DONE" in out
    assert "stale" not in out


def test_stale_verification_report_blocks_idle(tmp_path, fakes, capsys):
    """A verification report with no change to attach it to IS evidence of an
    aborted run — S5 only ever runs mid-change — so idle BLOCKS until it is
    cleaned up, on the bare run and on an explicit change-dependent stage."""
    root = make_root(tmp_path)
    (root / verify_report_path(root)).write_text("- PASS leftover\n")
    wg.list_changes = lambda root: []  # noqa: E731 — no workflow in progress
    rc, out = run_gate(root, capsys=capsys)
    assert rc == 1
    assert "stale" in out and "verification-report.md" in out
    rc, out = run_gate(root, "--stage", "S1", capsys=capsys)
    assert rc == 1
    assert "stale" in out


def test_s0_stale_verification_report_blocks(tmp_path, fakes, capsys):
    """A leftover verification report also trips the stale guard even when no
    gap report exists (explicit change-dependent --stage path)."""
    root = make_root(tmp_path, gap_report=False)
    (root / verify_report_path(root)).write_text("- PASS probe\n")
    wg.list_changes = lambda root: []  # noqa: E731 — no workflow in progress
    rc, out = run_gate(root, "--stage", "S1", capsys=capsys)
    assert rc == 1
    assert "stale" in out
    assert "verification-report.md" in out


def test_s1_and_bare_run_idle_when_no_workflow(tmp_path, fakes, capsys):
    """Change-dependent stages stay optional when no workflow is in progress
    and no stale .pipeline/ report lingers: --stage S1 reports idle (exit 0).
    A bare run on the same tree also reports idle."""
    root = make_root(tmp_path, gap_report=False)
    wg.list_changes = lambda root: []  # noqa: E731 — no workflow in progress
    rc, out = run_gate(root, "--stage", "S1", capsys=capsys)
    assert rc == 0
    assert "GATE idle" in out
    assert "no workflow in progress" in out
    rc, out = run_gate(root, capsys=capsys)
    assert rc == 0
    assert "GATE idle" in out


# ------------------------------------------------------------ S1 domain-spec

def test_s1_forward_blocked_done(tmp_path, fakes, capsys):
    root = make_root(tmp_path)
    # BLOCKED: proposal/specs not all done (design is S2's artifact now)
    wg.query_status = lambda root, change: fake_status({"proposal": "done", "specs": "blocked", "design": "done"})  # noqa: E731
    write_change(root)
    rc, out = run_gate(root, "--stage", "S1", capsys=capsys)
    assert rc == 1
    assert "GATE S1 domain-spec BLOCKED" in out
    assert "specs" in out
    # DONE: proposal+specs done — review: none, so no READY/sign-off state
    wg.query_status = lambda root, change: fake_status(PLANNING_DONE)  # noqa: E731
    write_change(root)  # no overrides at all
    rc, out = run_gate(root, "--stage", "S1", capsys=capsys)
    assert rc == 0
    assert "GATE S1 domain-spec DONE" in out


def test_s1_without_design_passes(tmp_path, fakes, capsys):
    """S1's scoping is proposal + specs only: design is S2's artifact, so S1
    reaches DONE even when design is not yet done."""
    root = make_root(tmp_path)
    write_change(root)
    wg.query_status = lambda root, change: fake_status({"proposal": "done", "specs": "done", "design": "blocked"})  # noqa: E731
    rc, out = run_gate(root, "--stage", "S1", capsys=capsys)
    assert rc == 0
    assert "GATE S1 domain-spec DONE" in out


def test_s1_no_signoff_required(tmp_path, fakes, capsys):
    """S1 (domain-spec) has review: none — proposal+specs done with NO
    overrides at all reaches DONE (no sign-off record is required)."""
    root = make_root(tmp_path)
    write_change(root)  # no overrides
    rc, out = run_gate(root, "--stage", "S1", capsys=capsys)
    assert rc == 0
    assert "GATE S1 domain-spec DONE" in out


def test_s1_kb_validate_failure_blocks(tmp_path, fakes, capsys):
    root = make_root(tmp_path)
    write_change(root)
    wg.run_kb_validate = lambda root, cfg=None: (False, "ERROR: docs/foo.md: bad\n")  # noqa: E731
    rc, out = run_gate(root, "--stage", "S1", capsys=capsys)
    assert rc == 1
    assert "GATE S1 domain-spec BLOCKED" in out
    assert "kb_validate" in out


# ------------------------------------------------------------ revision flow

def test_revision_done_to_ready_then_resign(tmp_path, fakes, capsys):
    root = make_root(tmp_path)
    seed_artifacts(root)
    write_change(root, overrides=[signoff("architecture")])
    rc, out = run_gate(root, "--stage", "S2", capsys=capsys)
    assert rc == 0
    assert "GATE S2 architecture DONE" in out
    # DONE -> READY: a revision record reopens the stage
    write_change(root, overrides=[signoff("architecture"), revision("architecture")])
    rc, out = run_gate(root, "--stage", "S2", capsys=capsys)
    assert rc == 1
    assert "GATE S2 architecture READY" in out
    assert "revised" in out
    # re-sign after revision -> DONE again
    write_change(root, overrides=[signoff("architecture"), revision("architecture"), signoff("architecture")])
    rc, out = run_gate(root, "--stage", "S2", capsys=capsys)
    assert rc == 0
    assert "GATE S2 architecture DONE" in out


def test_downstream_revalidation_is_downstream_only(tmp_path, fakes, capsys):
    root = make_root(tmp_path)
    seed_artifacts(root)
    write_change(root, overrides=SIGNOFFS_UP_TO["S3"])
    rc, out = run_gate(root, "--stage", "S3", capsys=capsys)
    assert rc == 0
    # revising S2 reopens S2 and blocks S3 until S2 is re-signed
    write_change(root, overrides=[*SIGNOFFS_UP_TO["S3"], revision("architecture")])
    rc, out = run_gate(root, "--stage", "S3", capsys=capsys)
    assert rc == 1
    assert "GATE S3 tasks BLOCKED" in out
    assert "upstream stage architecture" in out
    # S2 re-signed; S3's OWN conditions still hold -> DONE without a new S3 sign-off
    write_change(root, overrides=[*SIGNOFFS_UP_TO["S3"], revision("architecture"), signoff("architecture")])
    rc, out = run_gate(root, "--stage", "S3", capsys=capsys)
    assert rc == 0
    assert "GATE S3 tasks DONE" in out


# ------------------------------------------------------------ guardrails

def test_guardrail_archive_none_rejected_at_s6(tmp_path, fakes, capsys):
    root = make_root(tmp_path)
    write_change(root, stages={"archive": {"review": "none"}})
    rc, out = run_gate(root, "--stage", "S6", capsys=capsys)
    assert rc == 1
    assert "GATE ERROR" in out
    assert "guardrail" in out
    assert "archive" in out


def test_guardrail_archive_none_rejected_at_s0(tmp_path, fakes, capsys):
    root = make_root(tmp_path)
    write_change(root, stages={"archive": {"review": "none"}})
    rc, out = run_gate(root, "--stage", "S0", "--change", CHANGE, capsys=capsys)
    assert rc == 1
    assert "GATE ERROR" in out
    assert "archive" in out


def test_automated_implement_verify_have_no_review_gate(tmp_path, fakes, capsys):
    root = make_root(tmp_path)
    seed_artifacts(root)
    write_change(root, overrides=SIGNOFFS_UP_TO["S5"])
    rc, out = run_gate(root, "--stage", "S5", capsys=capsys)
    assert rc == 0
    assert "GATE S5 verify DONE" in out

def test_guardrail_default_config_violation(tmp_path, fakes, capsys):
    root = make_root(tmp_path)
    # Edit the config structurally: a raw string replace silently no-ops
    # against a re-serialised workflow.yaml, and the test then passes for the
    # wrong reason (or fails on an unrelated upstream stage).
    set_config(root, stages={"archive": {"review": "none"}})
    rc, out = run_gate(root, "--stage", "S6", capsys=capsys)
    assert rc == 1
    assert "guardrail" in out


# ------------------------------------------------------------ overrides

def test_override_merge_and_record(tmp_path, fakes, capsys):
    root = make_root(tmp_path)
    seed_artifacts(root)
    # tasks: default human -> agent (recorded)
    write_change(root, stages={"tasks": {"review": "agent"}},
                 overrides=[*SIGNOFFS_UP_TO["S2"],
                           {"key": "stages.tasks.review", "after": "agent", "by": "user", "when": "2026-08-13"},
                            signoff("tasks", by="agent")])
    rc, out = run_gate(root, "--stage", "S3", capsys=capsys)
    assert rc == 0
    assert "GATE S3 tasks DONE" in out
    assert "review: agent (override, recorded)" in out


def test_unrecorded_override_rejected(tmp_path, fakes, capsys):
    root = make_root(tmp_path)
    write_change(root, stages={"tasks": {"review": "agent"}})
    rc, out = run_gate(root, "--stage", "S3", capsys=capsys)
    assert rc == 1
    assert "GATE ERROR" in out
    assert "unrecorded override stages.tasks.review -> agent" in out


def test_unrecorded_coding_flow_override_rejected(tmp_path, fakes, capsys):
    root = make_root(tmp_path)
    write_change(root, coding_flow="autonomous")
    rc, out = run_gate(root, "--stage", "S0", "--change", CHANGE, capsys=capsys)
    assert rc == 1
    assert "unrecorded override coding_flow -> autonomous" in out


def test_recorded_coding_flow_override_ok(tmp_path, fakes, capsys):
    root = make_root(tmp_path)
    write_change(root, coding_flow="autonomous",
                 overrides=[{"key": "coding_flow", "after": "autonomous", "by": "user", "when": "2026-08-13"}])
    rc, out = run_gate(root, "--stage", "S0", "--change", CHANGE, capsys=capsys)
    assert rc == 0
    assert "GATE S0 intake DONE" in out


def test_malformed_record_rejected(tmp_path, fakes, capsys):
    root = make_root(tmp_path)
    write_change(root, overrides=[{"key": "signoff.architecture", "after": "approved", "by": "user"}])  # missing when
    rc, out = run_gate(root, "--stage", "S2", capsys=capsys)
    assert rc == 1
    assert "GATE ERROR" in out
    assert "missing or empty fields" in out


def test_handwritten_unquoted_record_dates_parse(tmp_path, fakes, capsys):
    # Hand-written change configs use unquoted ISO dates (`when: 2026-08-13`),
    # which PyYAML would otherwise turn into datetime objects.
    root = make_root(tmp_path)
    seed_artifacts(root)
    change_dir = root / layout(root)["changes_dir"] / CHANGE
    change_dir.mkdir(parents=True, exist_ok=True)
    (change_dir / ".openspec.yaml").write_text(
        "schema: spec-driven\n"
        "created: 2026-08-13\n"
        "overrides:\n"
        "  - key: signoff.architecture\n"
        "    after: approved\n"
        "    by: user\n"
        "    when: 2026-08-13\n"
    )
    rc, out = run_gate(root, "--stage", "S2", capsys=capsys)
    assert rc == 0
    assert "GATE S2 architecture DONE" in out


def test_unknown_record_key_rejected(tmp_path, fakes, capsys):
    root = make_root(tmp_path)
    write_change(root, overrides=[{"key": "signoff.doman-spec", "after": "approved", "by": "user", "when": "2026-08-13"}])
    rc, out = run_gate(root, "--stage", "S1", capsys=capsys)
    assert rc == 1
    assert "unknown overrides record key" in out
    assert "signoff.doman-spec" in out


# ------------------------------------------------------------ S2..S7 checks

def test_s2_adr_reference_required(tmp_path, fakes, capsys):
    root = make_root(tmp_path)
    seed_artifacts(root, adr_ref=False)
    write_change(root, overrides=SIGNOFFS_UP_TO["S2"])
    rc, out = run_gate(root, "--stage", "S2", capsys=capsys)
    assert rc == 1
    assert "GATE S2 architecture BLOCKED" in out
    assert "without an ADR reference" in out
    # with the ADR reference and sign-off -> DONE
    seed_artifacts(root, adr_ref=True)
    rc, out = run_gate(root, "--stage", "S2", capsys=capsys)
    assert rc == 0
    assert "GATE S2 architecture DONE" in out


def test_s2_no_adrs_at_all_blocks(tmp_path, fakes, capsys):
    root = make_root(tmp_path)
    seed_artifacts(root)
    (root / layout(root)["adr_dir"] / "0001-probe.md").unlink()
    write_change(root, overrides=SIGNOFFS_UP_TO["S2"])
    rc, out = run_gate(root, "--stage", "S2", capsys=capsys)
    assert rc == 1
    assert f"no ADRs found in {layout(root)['adr_dir']}/" in out


def test_s2_without_design_blocks(tmp_path, fakes, capsys):
    """S2 now requires the design artifact done on top of ADR references:
    design not done blocks even with ADRs in place."""
    root = make_root(tmp_path)
    seed_artifacts(root)  # ADR refs present
    write_change(root, overrides=SIGNOFFS_UP_TO["S2"])
    wg.query_status = lambda root, change: fake_status({"proposal": "done", "specs": "done", "design": "blocked"})  # noqa: E731
    rc, out = run_gate(root, "--stage", "S2", capsys=capsys)
    assert rc == 1
    assert "GATE S2 architecture BLOCKED" in out
    assert "design" in out


def test_s2_signoff_covers_s1_s2(tmp_path, fakes, capsys):
    """The combined S1+S2 human review happens at S2: signoff.architecture
    alone (no signoff.domain-spec) makes S2 DONE."""
    root = make_root(tmp_path)
    seed_artifacts(root)
    write_change(root, overrides=[signoff("architecture")])  # no signoff.domain-spec
    rc, out = run_gate(root, "--stage", "S2", capsys=capsys)
    assert rc == 0
    assert "GATE S2 architecture DONE" in out


def test_s2_rejected_signoff_is_revision_not_abort(tmp_path, fakes, capsys):
    """A rejected review is revision input, not an abort: the stage reports
    READY so the team revises and records a new sign-off."""
    root = make_root(tmp_path)
    seed_artifacts(root)
    write_change(root, overrides=[signoff("architecture", verdict="rejected")])
    rc, out = run_gate(root, "--stage", "S2", capsys=capsys)
    assert rc == 1
    assert "GATE S2 architecture READY" in out
    assert "rejected" in out
    assert "revision" in out


def test_s3_task_anchor_required(tmp_path, fakes, capsys):
    root = make_root(tmp_path)
    seed_artifacts(root, anchored=False)
    write_change(root, overrides=SIGNOFFS_UP_TO["S3"])
    rc, out = run_gate(root, "--stage", "S3", capsys=capsys)
    assert rc == 1
    assert "GATE S3 tasks BLOCKED" in out
    assert "without an anchor" in out
    seed_artifacts(root, anchored=True)
    rc, out = run_gate(root, "--stage", "S3", capsys=capsys)
    assert rc == 0
    assert "GATE S3 tasks DONE" in out


def test_s3_partial_valid_anchor_block_passes(tmp_path, fakes, capsys):
    root = make_root(tmp_path)
    seed_artifacts(root)
    tasks_path = root / layout(root)["changes_dir"] / CHANGE / "tasks.md"
    tasks_path.write_text(
        "- [x] probe task\n"
        "  - Domain: probe context\n"
    )
    write_change(root, overrides=SIGNOFFS_UP_TO["S3"])

    rc, out = run_gate(root, "--stage", "S3", capsys=capsys)

    assert rc == 0
    assert "GATE S3 tasks DONE" in out


def test_s3_blank_anchor_is_rejected(tmp_path, fakes, capsys):
    root = make_root(tmp_path)
    seed_artifacts(root)
    tasks_path = root / layout(root)["changes_dir"] / CHANGE / "tasks.md"
    tasks_path.write_text("- [x] probe task\n  - Domain:   \n")
    write_change(root, overrides=SIGNOFFS_UP_TO["S3"])

    rc, out = run_gate(root, "--stage", "S3", capsys=capsys)

    assert rc == 1
    assert "GATE S3 tasks BLOCKED" in out
    assert "without an anchor bullet" in out


def test_s3_no_tasks_blocks(tmp_path, fakes, capsys):
    root = make_root(tmp_path)
    seed_artifacts(root)  # upstream S2 needs the ADR on disk
    change_dir = root / layout(root)["changes_dir"] / CHANGE
    change_dir.mkdir(parents=True, exist_ok=True)
    (change_dir / "tasks.md").write_text("# Tasks\n\nNo tasks yet.\n")
    write_change(root, overrides=SIGNOFFS_UP_TO["S3"])
    rc, out = run_gate(root, "--stage", "S3", capsys=capsys)
    assert rc == 1
    assert "no '- [ ]' / '- [x]' tasks" in out


def test_s4_blocked_while_tasks_are_unchecked(tmp_path, fakes, monkeypatch, capsys):
    """The regression this check exists for: planning artifacts are all done,
    so openspec status reports isComplete=true, but not one task in tasks.md is
    ticked. Reading isComplete made S4 impossible to fail."""
    root = make_root(tmp_path)
    seed_artifacts(root)
    write_change(root, overrides=SIGNOFFS_UP_TO["S4"])
    monkeypatch.setattr(wg, "query_status", lambda root, change: fake_status(PLANNING_DONE, is_complete=True))
    monkeypatch.setattr(wg, "query_task_progress", lambda root, change: fake_progress(10, 0))
    rc, out = run_gate(root, "--stage", "S4", capsys=capsys)
    assert rc == 1
    assert "GATE S4 implement BLOCKED" in out
    assert "10 of 10" in out


def test_s4_blocked_on_the_last_unchecked_task(tmp_path, fakes, monkeypatch, capsys):
    root = make_root(tmp_path)
    seed_artifacts(root)
    write_change(root, overrides=SIGNOFFS_UP_TO["S4"])
    monkeypatch.setattr(wg, "query_task_progress", lambda root, change: fake_progress(10, 9))
    rc, out = run_gate(root, "--stage", "S4", capsys=capsys)
    assert rc == 1
    assert "1 of 10" in out


def test_s4_done_when_every_task_is_checked(tmp_path, fakes, monkeypatch, capsys):
    root = make_root(tmp_path)
    seed_artifacts(root)
    write_change(root, overrides=SIGNOFFS_UP_TO["S4"])
    monkeypatch.setattr(wg, "query_task_progress", lambda root, change: fake_progress(10, 10))
    rc, out = run_gate(root, "--stage", "S4", capsys=capsys)
    assert rc == 0
    assert "GATE S4 implement DONE" in out


def test_s4_fails_closed_when_progress_unreadable(tmp_path, fakes, monkeypatch, capsys):
    """A gate that cannot confirm must block, not wave the change through."""
    root = make_root(tmp_path)
    seed_artifacts(root)
    write_change(root, overrides=SIGNOFFS_UP_TO["S4"])
    monkeypatch.setattr(wg, "query_task_progress", lambda root, change: None)
    rc, out = run_gate(root, "--stage", "S4", capsys=capsys)
    assert rc == 1
    assert "GATE S4 implement BLOCKED" in out
    assert "task progress" in out


def test_s5_verify_report_required(tmp_path, fakes, capsys):
    root = make_root(tmp_path)
    seed_artifacts(root, report_passes=True)
    write_change(root, overrides=SIGNOFFS_UP_TO["S5"])
    (root / verify_report_path(root)).unlink()
    rc, out = run_gate(root, "--stage", "S5", capsys=capsys)
    assert rc == 1
    assert "missing verification report" in out
    # failed criteria block
    (root / verify_report_path(root)).write_text("- PASS a\n- FAIL b\n")
    rc, out = run_gate(root, "--stage", "S5", capsys=capsys)
    assert rc == 1
    assert "FAIL criteria" in out
    # tautological report (no PASS) blocks
    (root / verify_report_path(root)).write_text("nothing here\n")
    rc, out = run_gate(root, "--stage", "S5", capsys=capsys)
    assert rc == 1
    assert "tautological" in out
    # all pass + sign-off -> DONE
    (root / verify_report_path(root)).write_text("- PASS a\n- PASS b\n")
    rc, out = run_gate(root, "--stage", "S5", capsys=capsys)
    assert rc == 0
    assert "GATE S5 verify DONE" in out


def test_s6_archive_requires_validate_and_signoff(tmp_path, fakes, capsys):
    root = make_root(tmp_path)
    seed_artifacts(root)
    write_change(root, overrides=SIGNOFFS_UP_TO["S5"])
    # validate must pass
    wg.run_openspec_validate = lambda root, change: (False, "✗ change/feat-x\n")  # noqa: E731
    rc, out = run_gate(root, "--stage", "S6", capsys=capsys)
    assert rc == 1
    assert "GATE S6 archive BLOCKED" in out
    assert "validate" in out
    # sign-off required (archive review is human, never none)
    wg.run_openspec_validate = lambda root, change: (True, "")  # noqa: E731
    rc, out = run_gate(root, "--stage", "S6", capsys=capsys)
    assert rc == 1
    assert "GATE S6 archive READY" in out
    assert "sign-off" in out
    # both -> DONE
    write_change(root, overrides=SIGNOFFS_UP_TO["S6"])
    rc, out = run_gate(root, "--stage", "S6", capsys=capsys)
    assert rc == 0
    assert "GATE S6 archive DONE" in out


def test_s7_compound_kb_gate_no_signoff_needed(tmp_path, fakes, capsys):
    root = make_root(tmp_path)
    seed_artifacts(root)
    write_change(root, overrides=SIGNOFFS_UP_TO["S6"])
    wg.run_kb_validate = lambda root, cfg=None: (False, "ERROR: docs/foo.md\n")  # noqa: E731
    rc, out = run_gate(root, "--stage", "S7", capsys=capsys)
    assert rc == 1
    assert "GATE S7 compound BLOCKED" in out
    wg.run_kb_validate = lambda root, cfg=None: (True, "")  # noqa: E731
    rc, out = run_gate(root, "--stage", "S7", capsys=capsys)
    assert rc == 0
    assert "GATE S7 compound DONE" in out  # review: none — no sign-off needed


# ------------------------------------------------------------ post-archive

def test_archived_change_compound_done_and_pipeline_complete(tmp_path, fakes, capsys):
    """A change whose records live under openspec/changes/archive/<date>-<name>/
    (no active change) must still let the change-independent compound stage
    report DONE on its own KB condition, and the bare gate must report the
    pipeline complete — the archived sign-off trail is the evidence S1..S6
    passed pre-archive."""
    root = make_root(tmp_path)
    write_archived_change(root, overrides=SIGNOFFS_UP_TO["S6"])
    # A clean post-archive state has no transient reports.
    for report in ("gap-report.md", "verification-report.md"):
        report_path = root / layout(root)["pipeline_dir"] / report
        if report_path.exists():
            report_path.unlink()
    wg.list_changes = lambda root: []  # noqa: E731 — no active change
    # S7 compound DONE even though the change is archived
    rc, out = run_gate(root, "--stage", "S7", capsys=capsys)
    assert rc == 0
    assert "GATE S7 compound DONE" in out
    # bare gate: the final check reports the pipeline complete
    rc, out = run_gate(root, capsys=capsys)
    assert rc == 0
    assert "GATE S7 compound DONE" in out
    assert "pipeline complete" in out


def test_archived_change_with_leftover_report_blocks_stale_s0(tmp_path, fakes, capsys):
    """A bare post-archive check must not report archived S0 DONE while a
    transient gap or verification report remains to be cleaned up."""
    root = make_root(tmp_path)
    write_archived_change(root, overrides=SIGNOFFS_UP_TO["S6"])
    wg.list_changes = lambda root: []  # noqa: E731 — no active change
    rc, out = run_gate(root, capsys=capsys)
    assert rc == 1
    assert "GATE S0 intake BLOCKED" in out
    assert "stale .pipeline/ reports" in out
    assert "pipeline complete" not in out
def test_archived_change_without_transient_reports_skips_s0(tmp_path, fakes, capsys):
    """Archive cleanup removes transient reports without re-arming S0 for
    the already archived workflow, including explicit S7 and bare evaluation."""
    root = make_root(tmp_path)
    write_archived_change(root, overrides=SIGNOFFS_UP_TO["S6"])
    (root / verify_report_path(root)).write_text("- PASS archived\n")
    for report in ("gap-report.md", "verification-report.md"):
        (root / layout(root)["pipeline_dir"] / report).unlink()

    rc, out = run_gate(root, "--stage", "S7", capsys=capsys)
    assert rc == 0
    assert "GATE S7 compound DONE" in out

    rc, out = run_gate(root, capsys=capsys)
    assert rc == 0
    assert "pipeline complete" in out



def test_archived_change_resolved_by_name(tmp_path, fakes, capsys):
    root = make_root(tmp_path)
    write_archived_change(root, overrides=SIGNOFFS_UP_TO["S6"])
    (root / gap_report_path(root)).unlink()
    (root / verify_report_path(root)).unlink(missing_ok=True)
    rc, out = run_gate(root, "--change", CHANGE, capsys=capsys)
    assert rc == 0
    assert "GATE S7 compound DONE" in out
    assert "pipeline complete" in out


def test_archived_change_incomplete_trail_blocks(tmp_path, fakes, capsys):
    """The archive fallback must not weaken the audit trail: a change archived
    without a stage's approved sign-off still blocks that stage and any
    downstream compound gate."""
    root = make_root(tmp_path)
    write_archived_change(root, overrides=SIGNOFFS_UP_TO["S5"])  # missing signoff.archive
    (root / gap_report_path(root)).unlink()
    (root / verify_report_path(root)).unlink(missing_ok=True)
    rc, out = run_gate(root, "--stage", "S6", capsys=capsys)
    assert rc == 1
    assert "GATE S6 archive BLOCKED" in out
    assert "sign-off" in out
    rc, out = run_gate(root, "--stage", "S7", capsys=capsys)
    assert rc == 1
    assert "GATE S7 compound BLOCKED" in out
    assert "upstream stage archive" in out


def test_stage_gate_idle_when_no_workflow(tmp_path, fakes, capsys):
    """With no active change, nothing archived, and no stale .pipeline/ report,
    even an explicit --stage gate reports idle (exit 0): the gate is disabled
    when no workflow is in progress. Explicit --change still enforces (see
    test_change_not_found_blocks)."""
    root = make_root(tmp_path, gap_report=False)
    wg.list_changes = lambda root: []  # noqa: E731 — no active change
    (root / layout(root)["changes_dir"] / "archive").mkdir(parents=True, exist_ok=True)
    rc, out = run_gate(root, "--stage", "S1", capsys=capsys)
    assert rc == 0
    assert "GATE idle" in out
    assert "no workflow in progress" in out


def test_archived_change_name_match_is_anchored_not_suffixed(tmp_path, fakes, capsys):
    root = make_root(tmp_path)
    wg.list_changes = lambda root: []  # noqa: E731 — no active change
    write_archived_change(root, name="other-feat-x", overrides=SIGNOFFS_UP_TO["S6"])
    (root / gap_report_path(root)).unlink()
    (root / verify_report_path(root)).unlink(missing_ok=True)
    # `feat-x` is not a real change; it must not resolve to other-feat-x
    rc, out = run_gate(root, "--change", "feat-x", capsys=capsys)
    assert rc == 1
    assert "pipeline complete" not in out
    # the real change name still resolves post-archive
    rc, out = run_gate(root, "--change", "other-feat-x", capsys=capsys)
    assert rc == 0
    assert "pipeline complete" in out


# ------------------------------------------------------------ no-arg behavior

def test_bare_run_infers_single_change_and_reports_first_open_stage(tmp_path, fakes, capsys):
    root = make_root(tmp_path)
    write_change(root, overrides=SIGNOFFS_UP_TO["S2"])
    seed_artifacts(root)
    rc, out = run_gate(root, capsys=capsys)
    assert rc == 1
    assert "GATE S3 tasks READY" in out  # first stage not DONE: tasks sign-off missing


def test_bare_run_all_done_exits_zero(tmp_path, fakes, capsys):
    root = make_root(tmp_path)
    seed_artifacts(root)
    write_change(root, overrides=SIGNOFFS_UP_TO["S6"])
    rc, out = run_gate(root, capsys=capsys)
    assert rc == 0
    assert "GATE S7 compound DONE" in out


def test_bare_run_no_workflow_no_reports_is_idle(tmp_path, fakes, capsys):
    """A freshly installed harness: no change, no reports. Exit 0 so CI on a
    new project is green before any SDD work starts."""
    root = make_root(tmp_path, gap_report=False)
    wg.list_changes = lambda root: []  # noqa: E731
    rc, out = run_gate(root, capsys=capsys)
    assert rc == 0
    assert "GATE idle" in out


def test_multiple_changes_require_flag(tmp_path, fakes, capsys):
    root = make_root(tmp_path)
    wg.list_changes = lambda root: ["feat-a", "feat-b"]  # noqa: E731
    rc, out = run_gate(root, capsys=capsys)
    assert rc == 1
    assert "GATE ERROR" in out
    assert "pass --change" in out


def test_change_not_found_blocks(tmp_path, fakes, capsys):
    root = make_root(tmp_path)
    write_change(root)
    wg.query_status = lambda root, change: None  # noqa: E731
    rc, out = run_gate(root, "--stage", "S1", capsys=capsys)
    assert rc == 1
    assert "GATE S1 domain-spec BLOCKED" in out
    assert "not found" in out


# ------------------------------------------------------------ exit codes

def test_exit_code_contract(tmp_path, fakes, capsys):
    root = make_root(tmp_path)
    seed_artifacts(root)
    write_change(root, overrides=[signoff("architecture")])
    assert run_gate(root, "--stage", "S2", capsys=capsys)[0] == 0   # DONE
    write_change(root)  # no sign-off -> READY
    assert run_gate(root, "--stage", "S2", capsys=capsys)[0] == 1
    (root / gap_report_path(root)).unlink()  # S0 BLOCKED
    assert run_gate(root, "--stage", "S0", capsys=capsys)[0] == 1


# ------------------------------------------------- portability: paths / kb
#
# The harness ships to repos whose layout is not this one. These lock the
# contract that every path the gate touches comes from .openspec/workflow.yaml
# and that the knowledge-base check is genuinely optional.

def test_kb_defaults_to_disabled_and_needs_no_validator(tmp_path):
    """A repo with no knowledge base and no validator script still runs S1/S7.

    Asserted against the CODE default, not the shipped workflow.yaml: a
    destination that turns the knowledge base on must not fail this suite."""
    assert wg.DEFAULT_KB["enabled"] is False
    assert wg.kb_of({})["enabled"] is False
    root = make_root(tmp_path)
    set_config(root, kb={"enabled": False})
    assert not (root / "scripts" / "kb_validate.py").exists()
    cfg, _ = wg.load_workflow(root)
    assert wg.run_kb_validate(root, cfg) == (True, "")


def test_kb_enabled_without_validator_is_an_error(tmp_path):
    root = make_root(tmp_path)
    set_config(root, kb={"enabled": True, "validator": "scripts/nope.py"})
    cfg, _ = wg.load_workflow(root)
    with pytest.raises(wg.GateError) as exc:
        wg.run_kb_validate(root, cfg)
    assert "scripts/nope.py" in str(exc.value)


def test_kb_enabled_runs_the_configured_validator(tmp_path):
    root = make_root(tmp_path)
    (root / "scripts").mkdir(parents=True, exist_ok=True)
    (root / "scripts" / "kb_validate.py").write_text("import sys; sys.exit(0)\n")
    set_config(root, kb={"enabled": True})
    cfg, _ = wg.load_workflow(root)
    ok, _out = wg.run_kb_validate(root, cfg)
    assert ok


def test_kb_enabled_propagates_validator_failure(tmp_path):
    root = make_root(tmp_path)
    (root / "scripts").mkdir(parents=True, exist_ok=True)
    (root / "scripts" / "kb_validate.py").write_text(
        "import sys; print('ERROR: bad page'); sys.exit(1)\n"
    )
    set_config(root, kb={"enabled": True})
    cfg, _ = wg.load_workflow(root)
    ok, out = wg.run_kb_validate(root, cfg)
    assert not ok and "ERROR: bad page" in out


def test_paths_block_relocates_the_gap_report(tmp_path, capsys):
    root = make_root(tmp_path, gap_report=False)
    set_config(root, paths={"pipeline_dir": "build/sdd", "gap_report": "intake.md"})
    rc, out = run_gate(root, "--stage", "S0", capsys=capsys)
    assert rc == 1 and "build/sdd/intake.md" in out
    report = root / "build" / "sdd" / "intake.md"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text("# Gap report\n\nKnown: probe.\n")
    rc, out = run_gate(root, "--stage", "S0", capsys=capsys)
    assert rc == 0 and out.splitlines()[0].startswith("GATE S0 intake DONE")


def test_paths_block_relocates_the_adr_directory(tmp_path, fakes, capsys):
    root = make_root(tmp_path)
    write_change(root, overrides=SIGNOFFS_UP_TO["S2"])
    seed_artifacts(root)
    set_config(root, paths={"adr_dir": "architecture/decisions"})
    # The ADR seeded at the default location no longer counts.
    rc, out = run_gate(root, "--stage", "S2", capsys=capsys)
    assert rc == 1 and "architecture/decisions" in out
    adrs = root / "architecture" / "decisions"
    adrs.mkdir(parents=True, exist_ok=True)
    (adrs / "0001-probe.md").write_text("# ADR 0001: probe\n")
    rc, out = run_gate(root, "--stage", "S2", capsys=capsys)
    assert rc == 0 and out.splitlines()[0].startswith("GATE S2 architecture DONE")


def test_paths_block_relocates_the_verification_report(tmp_path, fakes, capsys):
    root = make_root(tmp_path)
    write_change(root, overrides=SIGNOFFS_UP_TO["S5"])
    seed_artifacts(root)
    set_config(root, paths={"pipeline_dir": "build/sdd"})
    moved_gap = root / "build" / "sdd" / "gap-report.md"
    moved_gap.parent.mkdir(parents=True, exist_ok=True)
    moved_gap.write_text("# Gap report\n\nKnown: probe.\n")
    rc, out = run_gate(root, "--stage", "S5", capsys=capsys)
    assert rc == 1 and "build/sdd/verification-report.md" in out
    report = root / "build" / "sdd" / "verification-report.md"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text("- PASS probe works\n")
    rc, out = run_gate(root, "--stage", "S5", capsys=capsys)
    assert rc == 0


def test_several_archived_changes_resolve_to_the_most_recent(tmp_path, monkeypatch, capsys):
    """Regression: erroring on >1 archived change made the bare gate — and so
    the Stop hook — fail permanently in any repo with real history."""
    root = make_root(tmp_path, gap_report=False)
    monkeypatch.setattr(wg, "list_changes", lambda root: [])
    monkeypatch.setattr(wg, "run_kb_validate", lambda root, cfg=None: (True, ""))
    monkeypatch.setattr(wg, "run_openspec_validate", lambda root, change: (True, ""))
    for date, name in (("2026-08-01", "feat-old"), ("2026-08-20", "feat-new")):
        write_archived_change(root, name=name, date=date, overrides=SIGNOFFS_UP_TO["S6"])
    assert wg.list_archived_changes(root, None) == ["feat-old", "feat-new"]
    rc, out = run_gate(root, capsys=capsys)
    assert "GATE ERROR" not in out
    assert rc == 0
