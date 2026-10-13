#!/usr/bin/env python3
"""workflow_gate.py — L1 gate for the SDD pipeline (see README.md).

The single source of truth for "may proceed": the gate verifies that the
requested stage's required artifacts exist and are valid and that
any required review sign-off is recorded, then exits 0 (proceed) or 1
(blocked). Claude Code hooks (piece 4) run this script bare and act on the
exit code.

CLI contract
------------
    python3 scripts/workflow_gate.py [--change <name>] [--stage <stage>] [--repo <root>]

    --change   OpenSpec change folder name (openspec/changes/<name>).
    --stage    Stage to gate: S0..S7 or the stage key from
               .openspec/workflow.yaml stage_index (intake, domain-spec,
               architecture, tasks, implement, verify, archive, compound).
               Default: the first stage in S0..S7 order whose gate does not
               pass ("what's next").
    --repo     Repo root (default: parent of this script's directory).

    Bare invocation (no --change): the change is inferred from
    `openspec list --json` — exactly one active change is required; multiple
    changes are reported as blocked/errors (pass --change). When no active
    change remains, the most recently archived change is resolved so the
    post-archive pipeline-complete check can report all stages DONE.

    No workflow in progress (no --change, no active change, no archived
    change): the change-dependent stages S1..S7 are OPTIONAL and report
    `GATE idle` with exit 0 — UNLESS a stale verification report from an
    aborted run is present, in which case idle is BLOCKED with exit 1 until
    it is cleaned up. A gap report alone is not stale: it is S0's output,
    written before the change exists. The pre-workflow admission stage S0 (intake) is the
    exception — its gap-report artifact precedes any change, so `--stage S0`
    (and a bare run whose first not-DONE stage is S0) still enforces the
    gap-report check and can BLOCK with exit 1.

Exit semantics
    Exit 0 — proceed: the stage gate passes (stage DONE).
    Exit 1 — blocked or error: artifacts missing/invalid, review sign-off
             missing, guardrail/recording violation, or config/usage error.
    The first stdout line is machine-readable for hooks:

        GATE <S#> <stage-key> <STATE>

    with STATE one of DONE, READY, BLOCKED, ERROR; reason lines follow,
    each prefixed with "- ".

States
    BLOCKED  required artifacts missing or invalid, or an upstream stage is
             not DONE (stages run in order; skipping forward is blocked).
    READY    artifacts valid but awaiting review sign-off — or the stage was
             revised (recorded DONE -> READY) and needs re-sign-off.
    DONE     artifacts valid and, for review-gated stages, an approved
             sign-off recorded (stages with review: none need no sign-off).

Records live under `overrides:` in the change's `.openspec.yaml`. Records are
append-only; the latest stage record wins. Required fields are `key`, `after`,
`by`, and `when`. Rationale is optional and ignored by the gate.

    overrides:
      - key: signoff.architecture
        after: approved
        by: user
        when: 2026-08-13

Review `none` is allowed for automated stages and forbidden only for archive.
Any policy override must have a matching record.

Repo layout is configuration, not code. Every path below comes from the
`paths:` block of .openspec/workflow.yaml (defaults in DEFAULT_PATHS), and the
knowledge-base check is opt-in via `kb:` (DEFAULT_KB, disabled by default).
The names used here are the defaults.

Per-stage artifact checks (transient reports live in <pipeline_dir>/):
    S0 intake       <pipeline_dir>/gap-report.md exists and is non-empty. When
                    no change is resolvable, a stale report (gap-report.md or
                    verification-report.md) from an aborted run BLOCKS the idle
                    short-circuit until cleaned up.
    S1 domain-spec  openspec status: proposal, specs done (design is S2's
                    artifact); and, when kb.enabled, the KB validator passes
                    (new pages). Review: none — S1's review is absorbed into
                    the combined S1+S2 human review at S2
                    (signoff.architecture).
    S2 architecture design artifact done (openspec status), every delta spec
                    under <changes_dir>/<name>/specs/** references an ADR
                    (<adr_dir>/... or ADR-<n>), and at least one ADR exists in
                    <adr_dir>/.
    S3 tasks        tasks.md has at least one "- [ ]"/"- [x]" task, and
                    every task carries at least one non-empty applicable anchor
                    sub-bullet (Domain: / Event contract: / Rule: / ADR: /
                    Infra: / Tests:).
    S4 implement    every task in tasks.md checked (openspec instructions
                    apply --json: progress.remaining == 0). NOT status
                    isComplete, which only reports planning artifacts.
    S5 verify       <pipeline_dir>/verification-report.md exists with >= 1
                    "- PASS <criterion>" line and 0 "- FAIL" lines.
    S6 archive      review sign-off (never none) AND `openspec validate
                    <change> --json` reports 0 failed items.
    S7 compound     when kb.enabled, the KB validator passes (whole-bundle
                    hygiene); a no-op when the KB check is disabled.

Cross-platform: pure Python 3 stdlib + PyYAML (see requirements.txt);
commands run without a shell (a shell fallback is
used only for the openspec.cmd shim on Windows; argv elements are internal
constants or a CHANGE_NAME_RE-validated change name).
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    print("ERROR: PyYAML is required. Install with: pip install pyyaml", file=sys.stderr)
    sys.exit(1)

REPO_ROOT = Path(__file__).resolve().parents[1]

# Default repo layout. Every entry is overridable from the `paths:` block of
# .openspec/workflow.yaml, so a destination repo adopts the harness by editing
# YAML rather than this file. Values are POSIX-style relative paths.
DEFAULT_PATHS = {
    "pipeline_dir": ".pipeline",
    "gap_report": "gap-report.md",
    "verification_report": "verification-report.md",
    "changes_dir": "openspec/changes",
    "adr_dir": "docs/adr",
}

# The knowledge-base check is OPT-IN. A destination repo without a KB runs the
# full pipeline with S1/S7 checking artifacts alone; turning it on adds the
# validator to both stages.
DEFAULT_KB = {
    "enabled": False,
    "root": "docs",
    "validator": "scripts/kb_validate.py",
}


def paths_of(cfg):
    """Merge the config's `paths:` block over DEFAULT_PATHS."""
    out = dict(DEFAULT_PATHS)
    block = (cfg or {}).get("paths")
    if isinstance(block, dict):
        for key, value in block.items():
            if key in out and isinstance(value, str) and value.strip():
                out[key] = value.strip()
    return out


def kb_of(cfg):
    """Merge the config's `kb:` block over DEFAULT_KB."""
    out = dict(DEFAULT_KB)
    block = (cfg or {}).get("kb")
    if isinstance(block, dict):
        if isinstance(block.get("enabled"), bool):
            out["enabled"] = block["enabled"]
        for key in ("root", "validator"):
            value = block.get(key)
            if isinstance(value, str) and value.strip():
                out[key] = value.strip()
    return out


def gap_report_rel(cfg):
    pth = paths_of(cfg)
    return Path(pth["pipeline_dir"]) / pth["gap_report"]


def verify_report_rel(cfg):
    pth = paths_of(cfg)
    return Path(pth["pipeline_dir"]) / pth["verification_report"]


def changes_dir(cfg):
    return Path(paths_of(cfg)["changes_dir"])


def archive_dir(cfg):
    return changes_dir(cfg) / "archive"


def adr_dir(cfg):
    return Path(paths_of(cfg)["adr_dir"])


def transient_reports(cfg):
    """The .pipeline/ reports whose presence outside a run means a stale tree."""
    return (gap_report_rel(cfg), verify_report_rel(cfg))


class _NoTimestampLoader(yaml.SafeLoader):
    """SafeLoader that keeps timestamp-looking scalars (e.g. the unquoted
    `when: 2026-08-13` record dates) as plain strings — mirrors
    scripts/kb_validate.py. Without this, PyYAML converts them to datetime
    objects and the record field checks below fail on hand-written YAML."""


_NoTimestampLoader.yaml_implicit_resolvers = {
    ch: [(tag, regexp) for tag, regexp in resolvers
         if tag != "tag:yaml.org,2002:timestamp"]
    for ch, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}

RECORD_FIELDS = ["key", "after", "by", "when"]  # workflow.yaml overrides.record.fields
CHANGE_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*[a-z0-9]$|^[a-z0-9]$")
TASK_RE = re.compile(r"^\s*-\s+\[[ xX]\]")
ANCHOR_RE = re.compile(
    r"^\s*[-*]\s+(Domain|Event contract|Rule|ADR|Infra|Tests):\s*(.*\S)\s*$"
)
ADR_REF_RE = re.compile(r"(?:docs/)?adr/|ADR[-: ]*\d+", re.IGNORECASE)
PASS_RE = re.compile(r"^\s*[-*]\s*(?:✅\s*)?PASS\b", re.MULTILINE)
FAIL_RE = re.compile(r"^\s*[-*]\s*(?:❌\s*)?FAIL\b", re.MULTILINE)


class GateError(Exception):
    """Configuration or usage problem — the gate cannot evaluate."""


# ---------------------------------------------------------------- IO seams

def _run(argv, cwd, timeout):
    """Run a command without a shell. On Windows only, retry through the
    shell when the direct exec fails (the `openspec` shim is a .cmd file);
    argv elements are internal constants or a validated change name, so the
    fallback cannot inject arguments."""
    try:
        proc = subprocess.run(argv, cwd=str(cwd), capture_output=True, text=True, timeout=timeout)
        return proc.returncode, proc.stdout or ""
    except subprocess.TimeoutExpired as exc:
        raise GateError(f"command timed out after {timeout}s: {' '.join(argv)}") from exc
    except OSError:
        if os.name != "nt":
            raise
    try:
        proc = subprocess.run(
            " ".join(argv), cwd=str(cwd), capture_output=True, text=True,
            timeout=timeout, shell=True,
        )
        return proc.returncode, proc.stdout or ""
    except subprocess.TimeoutExpired as exc:
        raise GateError(f"command timed out after {timeout}s: {' '.join(argv)}") from exc


def _openspec_bin():
    return shutil.which("openspec") or shutil.which("openspec.cmd")


def query_status(root, change):
    """`openspec status --change <name> --json` as parsed dict, or None when
    the change does not exist."""
    binary = _openspec_bin()
    if binary is None:
        raise GateError("openspec CLI not found on PATH (required for stages S1-S6)")
    rc, out = _run([binary, "status", "--change", change, "--json"], root, 30)
    if rc != 0:
        return None
    try:
        return json.loads(out)
    except json.JSONDecodeError as exc:
        raise GateError(f"openspec status returned invalid JSON for change {change!r}") from exc


def query_task_progress(root, change):
    """`openspec instructions apply --change <name> --json`'s progress block as
    a dict with total/complete/remaining, or None when it cannot be read.

    This, not `openspec status`, is what says whether the work is done:
    status.isComplete reports planning-artifact completeness (it equals
    isPlanningComplete), and is true the moment tasks.md exists.
    """
    binary = _openspec_bin()
    if binary is None:
        raise GateError("openspec CLI not found on PATH (required for stages S1-S6)")
    rc, out = _run([binary, "instructions", "apply", "--change", change, "--json"], root, 30)
    if rc != 0:
        return None
    try:
        progress = json.loads(out).get("progress")
    except json.JSONDecodeError:
        return None
    return progress if isinstance(progress, dict) else None


def list_changes(root):
    """Active change names from `openspec list --json`."""
    binary = _openspec_bin()
    if binary is None:
        raise GateError("openspec CLI not found on PATH")
    rc, out = _run([binary, "list", "--json"], root, 30)
    if rc != 0:
        raise GateError(f"openspec list failed (exit {rc})")
    try:
        data = json.loads(out)
    except json.JSONDecodeError as exc:
        raise GateError("openspec list returned invalid JSON") from exc
    return [c.get("name") for c in data.get("changes", [])]


def run_kb_validate(root, cfg):
    """Run the configured knowledge-base validator → (ok, output).

    Returns (True, "") when the KB check is disabled, so S1/S7 fall back to
    their artifact conditions alone in a repo with no knowledge base."""
    kb = kb_of(cfg)
    if not kb["enabled"]:
        return True, ""
    script = root / kb["validator"]
    if not script.is_file():
        raise GateError(
            f"kb.enabled is true but the validator is missing: {kb['validator']} "
            f"(set kb.validator in .openspec/workflow.yaml, or kb.enabled: false)"
        )
    rc, out = _run([sys.executable, str(script), kb["root"], "--quiet"], root, 120)
    return rc == 0, out


def run_kb_compound_check(root, cfg):
    """Run the compound check → (ok, output).

    (True, "") when the KB is disabled or the script is absent: compounding is
    an optional refinement of an already-optional knowledge base, so its
    absence must not block a repo that never opted in."""
    if not kb_of(cfg)["enabled"]:
        return True, ""
    script = root / "scripts" / "kb_compound.py"
    if not script.is_file():
        return True, ""
    rc, out = _run([sys.executable, str(script), "--check", "--repo", str(root)], root, 120)
    return rc == 0, out


def run_openspec_validate(root, change):
    """`openspec validate <change> --json` → (ok, output). The CLI exits 0
    even with failures, so the JSON summary is authoritative."""
    binary = _openspec_bin()
    rc, out = _run([binary, "validate", change, "--json"], root, 120)
    if rc != 0:
        raise GateError(f"openspec validate failed (exit {rc})")
    try:
        data = json.loads(out)
    except json.JSONDecodeError as exc:
        raise GateError("openspec validate returned invalid JSON") from exc
    totals = data.get("summary", {}).get("totals", {})
    return totals.get("failed", 0) == 0, out


# ---------------------------------------------------------------- config

def load_workflow(root):
    """Parse .openspec/workflow.yaml → (cfg, stage_order). Required sections
    are validated; optional sections fall back to their plan defaults."""
    path = root / ".openspec" / "workflow.yaml"
    if not path.is_file():
        raise GateError(f"missing workflow config: {path}")
    with open(path, encoding="utf-8") as fh:
        cfg = yaml.load(fh, Loader=_NoTimestampLoader) or {}
    if not isinstance(cfg, dict):
        raise GateError(f"workflow config {path} must be a YAML mapping")
    index = cfg.get("stage_index")
    stages = cfg.get("stages")
    if not isinstance(index, dict) or not isinstance(stages, dict):
        raise GateError(f"workflow config {path}: 'stage_index' and 'stages' mappings are required")
    order = {}
    for label, key in index.items():
        m = re.fullmatch(r"[Ss](\d+)", str(label))
        if not m or not isinstance(key, str):
            raise GateError(f"workflow config {path}: stage_index entry {label!r} -> {key!r} invalid (want S<num>: <key>)")
        order[int(m.group(1))] = key
    if not order:
        raise GateError(f"workflow config {path}: stage_index is empty")
    stage_order = [order[n] for n in sorted(order)]
    for key in stage_order:
        entry = stages.get(key)
        if not isinstance(entry, dict) or not isinstance(entry.get("review"), str):
            raise GateError(f"workflow config {path}: stage {key!r} needs 'review: none|human|agent'")
    cfg.setdefault("review", {"values": ["none", "human", "agent"]})
    cfg.setdefault("coding_flow", {"default": "standard", "allowed": ["standard", "validate", "autonomous"]})
    cfg.setdefault("guardrails", {}).setdefault("review", {"none_forbidden": []})
    cfg.setdefault("gates", {}).setdefault("review_condition", {"signoff_required": ["human", "agent"]})
    return cfg, stage_order


def change_config_path(root, name, cfg=None):
    """Locate a change's .openspec.yaml — the active folder first, then the
    archive (openspec/changes/archive/<date>-<name>/) as a fallback once the
    change has been archived. Returns (path | None, from_archive: bool).
    The active copy wins when both exist; multiple archive matches for the
    same name are ambiguous and reported as a GateError."""
    active = root / changes_dir(cfg) / name / ".openspec.yaml"
    if active.is_file():
        return active, False
    base = root / archive_dir(cfg)
    if base.is_dir():
        # Match ONLY directories named exactly <date>-<name> (YYYY-MM-DD-<name>).
        # A trailing `-<name>` glob would let `--change feat-x` resolve a
        # directory literally named `2026-08-14-other-feat-x` (glob collision).
        dirs = [
            p for p in sorted(base.glob("*/"))
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}-" + re.escape(name), p.name)
        ]
        matches = [p / ".openspec.yaml" for p in dirs if (p / ".openspec.yaml").is_file()]
        if len(matches) == 1:
            return matches[0], True
        if len(matches) > 1:
            raise GateError(
                f"multiple archived changes match {name!r}: "
                f"{', '.join(str(p.parent.name) for p in matches)}"
            )
    return None, False


def _read_yaml(path):
    """Parse a change's .openspec.yaml (custom keys pass through) — a mapping
    is required, mirroring the workflow.yaml loader."""
    with open(path, encoding="utf-8") as fh:
        cfg = yaml.load(fh, Loader=_NoTimestampLoader) or {}
    if not isinstance(cfg, dict):
        raise GateError(f"change config {path} must be a YAML mapping")
    return cfg


def load_change_config(root, name, cfg=None):
    """Parse a change's .openspec.yaml (custom keys pass through), falling
    back to the archived copy when the change has moved to
    openspec/changes/archive/<date>-<name>/. Returns None when the change has
    no config file (active or archived)."""
    path, _ = change_config_path(root, name, cfg)
    return _read_yaml(path) if path else None


def list_archived_changes(root, cfg=None):
    """Change names with a config under
    openspec/changes/archive/<date>-<name>/, date-sorted. Used to resolve the
    pipeline-complete check post-archive when no active change remains."""
    base = root / archive_dir(cfg)
    if not base.is_dir():
        return []
    names = []
    for folder in sorted(base.iterdir()):
        m = re.fullmatch(r"\d{4}-\d{2}-\d{2}-(.+)", folder.name)
        if m and (folder / ".openspec.yaml").is_file():
            names.append(m.group(1))
    return names


def records_of(change_cfg):
    """Normalize audit records in file order; malformed records are errors."""
    raw = change_cfg.get("overrides") or []
    if not isinstance(raw, list):
        raise GateError("change config 'overrides' must be a list of records")
    parsed = []
    for i, rec in enumerate(raw):
        if not isinstance(rec, dict):
            raise GateError(f"change config overrides record #{i} must be a mapping")
        missing = [f for f in RECORD_FIELDS if not isinstance(rec.get(f), str) or not rec[f]]
        if missing:
            raise GateError(f"change config overrides record #{i} ({rec.get('key')!r}) missing or empty fields: {missing}")
        parsed.append((rec["key"], rec["after"], rec["by"], rec["when"]))
    return parsed


def effective_policy(cfg, stage_order, change_cfg):
    """Merge change-level .openspec.yaml over defaults. Returns
    (reviews, coding_flow, defaults) and raises GateError on vocabulary or
    guardrail violations."""
    defaults = {k: cfg["stages"][k]["review"] for k in stage_order}
    reviews = dict(defaults)
    flow = cfg["coding_flow"]["default"]
    if change_cfg is not None:
        changed = change_cfg.get("stages") or {}
        if not isinstance(changed, dict):
            raise GateError("change config 'stages' must be a mapping")
        for key, entry in changed.items():
            if key not in defaults:
                raise GateError(f"change config overrides unknown stage {key!r}")
            if not isinstance(entry, dict) or not isinstance(entry.get("review"), str):
                raise GateError(f"change config stage {key!r} must map to {{review: none|human|agent}}")
            reviews[key] = entry["review"]
        if "coding_flow" in change_cfg:
            flow = change_cfg["coding_flow"]
    values = cfg["review"]["values"]
    for key, val in reviews.items():
        if val not in values:
            raise GateError(f"stage {key!r}: review {val!r} not in {values}")
    if flow not in cfg["coding_flow"]["allowed"]:
        raise GateError(f"coding_flow {flow!r} not in {cfg['coding_flow']['allowed']}")
    for key in cfg["guardrails"]["review"]["none_forbidden"]:
        if reviews.get(key) == "none":
            raise GateError(f"guardrail: review 'none' is forbidden for stage {key!r}")
    return reviews, flow, defaults


def check_record_keys(records, stage_order):
    """Reject records whose keys are not recognized policy or stage records."""
    known = {"coding_flow"}
    known.update(f"stages.{k}.review" for k in stage_order)
    known.update(f"signoff.{k}" for k in stage_order)
    known.update(f"revision.{k}" for k in stage_order)
    bad = sorted({key for key, *_ in records if key not in known})
    if bad:
        raise GateError(
            f"unknown overrides record key(s): {', '.join(bad)} "
            "(want stages.<stage>.review, coding_flow, signoff.<stage>, revision.<stage>)"
        )


def check_recorded(records, cfg, stage_order, reviews, flow, defaults):
    """Every effective override of a default must have a matching record.
    Returns violation strings (empty = OK)."""
    violations = []
    for key in stage_order:
        if reviews[key] != defaults[key] and not _recorded(records, f"stages.{key}.review", reviews[key]):
            violations.append(
                f"unrecorded override stages.{key}.review -> {reviews[key]} "
                "(add an overrides record with key, after, by, and when)"
            )
    if flow != cfg["coding_flow"]["default"] and not _recorded(records, "coding_flow", flow):
        violations.append(f"unrecorded override coding_flow -> {flow}")
    return violations


def _recorded(records, key, after):
    return any(r[0] == key and r[1] == after for r in records)


def stage_record(records, stage):
    """Latest sign-off/revision entry for a stage → (kind, after) | None."""
    latest = None
    for key, after, *_ in records:
        prefix, _, name = key.partition(".")
        if name == stage and prefix in ("signoff", "revision"):
            latest = (prefix, after)
    return latest


# ---------------------------------------------------------------- checks

def check_artifacts(stage, root, change, status, cfg=None):
    """(ok, reasons) for the stage's required artifacts."""
    if stage == "intake":
        rel = gap_report_rel(cfg)
        report = root / rel
        ok = report.is_file() and bool(report.read_text(encoding="utf-8", errors="replace").strip())
        return ok, [] if ok else [f"missing gap report: {rel} (Stage 0 output)"]
    if stage == "compound":
        ok, out = run_kb_validate(root, cfg)
        if not ok:
            reasons = [f"{kb_of(cfg)['validator']} reports errors (the knowledge base is invalid)"]
            return False, reasons + _tail(out)
        # The KB is valid; is the archived change actually folded into it?
        ok, out = run_kb_compound_check(root, cfg)
        reasons = [] if ok else ["the archived change is not folded into the knowledge base yet (scripts/kb_compound.py)"]
        return ok, reasons + _tail(out)
    if change is None:
        return False, ["no change selected (create one, or pass --change <name>)"]
    if stage == "domain-spec":
        ok, reasons = _planning_done(status, ("proposal", "specs"))
        if ok:
            kb_ok, kb_out = run_kb_validate(root, cfg)
            if not kb_ok:
                reasons = [f"{kb_of(cfg)['validator']} reports errors (new KB pages must validate)"] + _tail(kb_out)
            ok = kb_ok
        return ok, reasons
    if stage == "architecture":
        ok, reasons = _planning_done(status, ("design",))
        if ok:
            adr_ok, adr_reasons = _adr_refs(root, change, cfg)
            ok, reasons = adr_ok, adr_reasons
        return ok, reasons
    if stage == "tasks":
        return _tasks_anchored(root, change, cfg)
    if stage == "implement":
        return _change_complete(root, change)
    if stage == "verify":
        return _verify_report(root, cfg)
    if stage == "archive":
        ok, out = run_openspec_validate(root, change)
        reasons = [] if ok else ["openspec validate reports failures (fix the delta specs before archive)"]
        return ok, reasons + _tail(out)
    raise GateError(f"no artifact check defined for stage {stage!r}")


def _tail(out, limit=10):
    return [ln.strip() for ln in (out or "").splitlines() if ln.strip()][:limit]


def _planning_done(status, need=("proposal", "specs", "design")):
    states = {a.get("id"): a.get("status") for a in status.get("artifacts", [])} if status else {}
    missing = [a for a in need if states.get(a) != "done"]
    if missing:
        return False, [f"planning artifact(s) not done: {', '.join(missing)}"]
    return True, []


def _adr_refs(root, change, cfg=None):
    rel_adr = adr_dir(cfg)
    adrs = root / rel_adr
    if not adrs.is_dir() or not list(adrs.glob("*.md")):
        return False, [f"no ADRs found in {rel_adr}/ (Stage 2 must produce ADRs)"]
    specs_dir = root / changes_dir(cfg) / change / "specs"
    unreferenced = []
    if specs_dir.is_dir():
        for spec in sorted(specs_dir.rglob("*.md")):
            text = spec.read_text(encoding="utf-8", errors="replace")
            if not ADR_REF_RE.search(text):
                unreferenced.append(str(spec.relative_to(root)))
    if unreferenced:
        return False, [f"delta spec(s) without an ADR reference ({rel_adr}/… or ADR-<n>): {', '.join(unreferenced)}"]
    return True, []


def _tasks_anchored(root, change, cfg=None):
    path = root / changes_dir(cfg) / change / "tasks.md"
    if not path.is_file():
        return False, ["missing tasks.md in change folder"]
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    task_indexes = [i for i, ln in enumerate(lines) if TASK_RE.match(ln)]
    if not task_indexes:
        return False, ["tasks.md has no '- [ ]' / '- [x]' tasks"]

    # Each task owns the lines up to the next checkbox task.  A task must
    # name at least one applicable anchor; the other categories are optional.
    unanchored = []
    for pos, idx in enumerate(task_indexes):
        end = task_indexes[pos + 1] if pos + 1 < len(task_indexes) else len(lines)
        found = set()
        for line in lines[idx + 1:end]:
            match = ANCHOR_RE.match(line)
            if match:
                found.add(match.group(1))
        task_label = lines[idx].strip()
        if not found:
            unanchored.append(task_label)
    if unanchored:
        return False, [f"task(s) without an anchor bullet (Domain:/Event contract:/Rule:/ADR:/Infra:/Tests:): {', '.join(unanchored[:4])}"]
    return True, []


def _change_complete(root, change):
    progress = query_task_progress(root, change)
    if not progress:
        return False, ["cannot read task progress (openspec instructions apply --json returned no progress block)"]
    remaining, total = progress.get("remaining"), progress.get("total")
    if not isinstance(remaining, int) or not isinstance(total, int):
        return False, ["cannot read task progress (progress block has no integer total/remaining)"]
    if remaining:
        return False, [f"{remaining} of {total} task(s) in tasks.md are still unchecked"]
    return True, []


def _verify_report(root, cfg=None):
    rel = verify_report_rel(cfg)
    report = root / rel
    if not report.is_file():
        return False, [f"missing verification report: {rel} (Stage 5 output)"]
    text = report.read_text(encoding="utf-8", errors="replace")
    fails = len(FAIL_RE.findall(text))
    passes = len(PASS_RE.findall(text))
    if fails:
        return False, [f"verification report has {fails} FAIL criteria (need zero — fix and re-verify)"]
    if not passes:
        return False, [f"verification report has no PASS criteria ({rel} is tautological)"]
    return True, []


# ---------------------------------------------------------------- gate

def evaluate_stage(stage, stage_num, stage_order, root, change, status, cfg,
                   records, reviews, defaults, memo, archived=False):
    """(state, reasons, review_label) for one stage — BLOCKED | READY | DONE.
    Upstream stages must be DONE first (stages run in order); a revision on
    an upstream stage revalidates this stage's own conditions fresh
    (downstream-only revalidation, backward flow).

    `archived` marks a change resolved from openspec/changes/archive/ (the
    post-archive state): its live artifacts are no longer readable via the
    openspec CLI, so the change-dependent stages S1..S6 report DONE from
    their recorded approved sign-offs — the audit trail is never bypassed,
    only re-reading the frozen artifacts is skipped."""
    if stage in memo:
        return memo[stage]
    for m in range(stage_num):
        up_state, up_reasons, _ = evaluate_stage(
            stage_order[m], m, stage_order, root, change, status, cfg,
            records, reviews, defaults, memo, archived,
        )
        if up_state != "DONE":
            detail = f" ({up_reasons[0]})" if up_reasons else ""
            result = ("BLOCKED", [f"upstream stage {stage_order[m]} is {up_state}{detail}"], "")
            memo[stage] = result
            return result
    review = reviews[stage]
    label = f"review: {review} ({'override, recorded' if review != defaults[stage] else 'default'})"
    # Change-independent stages (S0 intake, S7 compound) gate repo-level
    # artifacts only and never need change resolution; short-circuit so S7
    # stays evaluable post-archive when the change has moved out of
    # openspec/changes/<name>/.
    if stage in ("intake", "compound"):
        if archived and stage == "intake":
            # A bare post-archive check is complete only after transient
            # reports have been removed. Any leftover report is evidence of an
            # incomplete archive cleanup and must block as stale.
            stale = [p.name for p in transient_reports(cfg) if (root / p).is_file()]
            if stale:
                result = (
                    "BLOCKED",
                    [f"stale .pipeline/ reports ({', '.join(stale)}) from an archived run — clean up before reporting completion"],
                    f"archived: {label}",
                )
                memo[stage] = result
                return result
            result = ("DONE", [], f"archived: {label}")
            memo[stage] = result
            return result
        ok, reasons = check_artifacts(stage, root, change, status, cfg)
        if not ok:
            result = ("BLOCKED", reasons, label)
            memo[stage] = result
            return result
        result = ("DONE", [], label)
        memo[stage] = result
        return result
    if archived:
        # Post-archive: the archived sign-off record is the evidence the
        # stage was passed pre-archive. Require the approved record so an
        # incomplete audit trail still blocks. Stages whose effective review
        # is `none` never record a sign-off (S1), so they need no record.
        latest = stage_record(records, stage)
        if review in cfg["gates"]["review_condition"]["signoff_required"]:
            if latest == ("signoff", "approved"):
                result = ("DONE", [], f"archived: {label}")
                memo[stage] = result
                return result
            result = (
                "BLOCKED",
                [f"archived change {change!r} missing approved sign-off for {stage} (audit trail incomplete)"],
                label,
            )
            memo[stage] = result
            return result
        result = ("DONE", [], f"archived: {label}")
        memo[stage] = result
        return result
    if change is None:
        result = ("BLOCKED", ["no change selected (create a change, or pass --change <name>)"], "")
        memo[stage] = result
        return result
    if status is None and stage in ("domain-spec", "architecture", "tasks", "implement"):
        result = ("BLOCKED", [f"change {change!r} not found"], "")
        memo[stage] = result
        return result
    ok, reasons = check_artifacts(stage, root, change, status, cfg)
    if not ok:
        result = ("BLOCKED", reasons, label)
        memo[stage] = result
        return result
    if review in cfg["gates"]["review_condition"]["signoff_required"]:
        latest = stage_record(records, stage)
        if latest is None:
            result = (
                "READY",
                [f"no review sign-off recorded for {stage} (review: {review}) — add an overrides record with key signoff.{stage}, after: approved"],
                label,
            )
        elif latest[0] == "signoff" and latest[1] == "approved":
            result = ("DONE", [], label)
        elif latest[0] == "signoff" and latest[1] == "rejected":
            result = (
                "READY",
                [f"review for {stage} was rejected — revise the stage artifacts and record a new sign-off (rejection is revision input, not an abort)"],
                label,
            )
        elif latest[0] == "revision":
            result = (
                "READY",
                [f"stage {stage} was revised (recorded DONE -> {latest[1]}) — re-record sign-off once the artifacts are corrected"],
                label,
            )
        else:
            result = ("READY", [f"invalid record for {stage}: key {latest[0]}.{stage} after={latest[1]!r}"], label)
    else:
        result = ("DONE", [], label)
    memo[stage] = result
    return result


def resolve_stage(arg, cfg):
    """--stage arg → (stage_num, stage_key)."""
    if arg.upper() in cfg["stage_index"]:
        label = arg.upper()
        return int(label[1:]), cfg["stage_index"][label]
    for label, key in cfg["stage_index"].items():
        if arg == key:
            return int(label[1:]), key
    raise GateError(
        f"unknown stage {arg!r} — use S0..S7 or one of: {', '.join(sorted(cfg['stage_index'].values()))}"
    )


def _report(stage_num, stage_key, state, reasons, label):
    if state == "DONE":
        print(f"GATE S{stage_num} {stage_key} DONE: may proceed")
        print(f"  {label}")
        return 0
    first = reasons[0] if reasons else state.lower()
    print(f"GATE S{stage_num} {stage_key} {state}: {first}")
    print(f"  {label}")
    for reason in reasons[1:]:
        print(f"  - {reason}")
    return 1


def _main(args):
    root = args.repo.resolve()
    cfg, stage_order = load_workflow(root)
    requested = resolve_stage(args.stage, cfg) if args.stage is not None else None
    change = args.change
    if change is not None:
        if not CHANGE_NAME_RE.fullmatch(change):
            raise GateError(f"invalid change name {change!r} (lowercase alphanumeric with hyphens)")
    elif requested is None or requested[1] != "intake":
        names = list_changes(root)
        if len(names) == 1:
            change = names[0]
        elif len(names) > 1:
            raise GateError(f"{len(names)} active changes ({', '.join(names)}) — pass --change <name>")
        elif not names and (requested is None or requested[1] != "intake"):
            # No active change: the pipeline may already be complete and the
            # change archived. Resolve a single archived change so the final
            # check can report all stages DONE post-archive. Explicit S0 is
            # admission for a new workflow and must not inherit archive state.
            archived = list_archived_changes(root, cfg)
            if archived:
                # Date-sorted; the most recent archive is the workflow that
                # just finished, and the one the post-archive completion
                # check is about. Erroring on >1 instead would make the bare
                # gate — and therefore the Stop hook — fail permanently in
                # any repo that has archived more than one change.
                change = archived[-1]
    # S0 intake is a PRE-WORKFLOW admission stage: its artifact (the gap
    # report, .pipeline/gap-report.md) precedes any change, so it must be
    # enforced even when no workflow is in progress (the L1 hook gates
    # `openspec new change` with --stage S0 BEFORE a change exists). Only
    # the change-dependent stages S1..S7 are optional when no change is
    # resolvable — that idle short-circuit is applied at the
    # per-stage gate points below, not here, so S0 still evaluates.
    # Explicit S0 is a fresh admission check for the gap report, but an
    # active selected change still supplies policy/guardrail configuration.
    # Only archived metadata (or no selected change) is bypassed on admission.
    admission_only = requested is not None and requested[1] == "intake"
    change_cfg = None
    from_archive = False
    if change is not None:
        path, from_archive = change_config_path(root, change, cfg)
        if path and (not from_archive or not admission_only):
            change_cfg = _read_yaml(path)
    reviews, flow, defaults = effective_policy(cfg, stage_order, change_cfg)
    records = records_of(change_cfg) if change_cfg else []
    check_record_keys(records, stage_order)
    violations = check_recorded(records, cfg, stage_order, reviews, flow, defaults)
    if violations:
        print("GATE ERROR: recording violations (the audit trail is never bypassed)")
        for violation in violations:
            print(f"  - {violation}")
        return 1
    # Archived and active change status is irrelevant to explicit S0; avoid
    # invoking the CLI at all on this pre-workflow admission path.
    status = query_status(root, change) if change and not from_archive and not admission_only else None
    memo = {}

    def _idle():
        # A verification report with no change to attach it to is evidence of
        # an aborted run: S5 only ever runs mid-change. A gap report alone is
        # NOT — it is S0's output, written BEFORE `openspec new change`, so
        # treating it as stale would block the turn that produced it.
        verify_rel = verify_report_rel(cfg)
        if (root / verify_rel).is_file():
            print(
                f"GATE idle BLOCKED: stale report ({verify_rel.name}) from an aborted run "
                f"— clean up before starting S0"
            )
            return 1
        if (root / gap_report_rel(cfg)).is_file():
            print("GATE idle: S0 intake DONE — create a change to continue (no active change)")
            return 0
        print(
            "GATE idle: no workflow in progress — Stage 0 starts a change "
            f"(write {gap_report_rel(cfg)}, see templates/gap-report.md)"
        )
        return 0

    if args.stage is None:
        # Nothing in flight and Stage 0 not started: the bare run answers
        # "what's next", and the answer is "nothing yet" — not BLOCKED.
        # S0 admission is enforced on the EXPLICIT `--stage S0` path, which is
        # what the PreToolUse hooks call before `openspec new change`; nothing
        # is weakened here. Reporting exit 1 instead would fail CI on every
        # repo that simply is not mid-change.
        if change is None and not (root / gap_report_rel(cfg)).is_file():
            return _idle()
        for num, key in enumerate(stage_order):
            if change is None and key != "intake":
                # No workflow in progress and the first not-DONE stage is a
                # change-dependent one (S1..S7): the gate is optional (plan
                # §8). S0 intake is evaluated above (or here, first) because
                # its gap-report artifact precedes any change.
                return _idle()
            state, reasons, label = evaluate_stage(
                key, num, stage_order, root, change, status, cfg,
                records, reviews, defaults, memo, from_archive,
            )
            if state != "DONE":
                return _report(num, key, state, reasons, label)
        num, key = len(stage_order) - 1, stage_order[-1]
        return _report(num, key, "DONE", [], "pipeline complete (all stages DONE)")
    stage_num, stage_key = requested
    if change is None and stage_key != "intake":
        # Idle applies only to change-dependent stages; S0 intake is a
        # pre-workflow admission gate and always evaluates its artifact.
        return _idle()
    # Explicit S0 is a fresh admission check even when --change names an
    # archived workflow; bare and later explicit stages retain archive completion.
    evaluation_archived = from_archive and stage_key != "intake"
    state, reasons, label = evaluate_stage(
        stage_key, stage_num, stage_order, root, change, status, cfg,
        records, reviews, defaults, memo, evaluation_archived,
    )
    return _report(stage_num, stage_key, state, reasons, label)


def main(argv=None):
    parser = argparse.ArgumentParser(description="SDD pipeline stage gate")
    parser.add_argument("--change", metavar="NAME", help="openspec change folder name")
    parser.add_argument("--stage", metavar="S#|KEY", help="stage to gate (S0..S7 or stage key); default: first stage not yet DONE")
    parser.add_argument("--repo", metavar="ROOT", type=Path, default=REPO_ROOT, help="repo root (default: parent of scripts/)")
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        return 1  # argparse usage errors exit 2; the gate contract is 0/1
    try:
        return _main(args)
    except GateError as exc:
        print(f"GATE ERROR: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
