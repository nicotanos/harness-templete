# SDD Pipeline — Running a Change

This repo runs an **artifact-enforced, spec-driven development (SDD) pipeline**:
every product change moves through eight stages (S0–S7), each producing required
artifacts in an OpenSpec change folder (`openspec/changes/<name>/`), verified by
a gate script (`scripts/workflow_gate.py`) before proceeding. Setup and
configuration: [README.md](README.md). Operating narrative: the `sdd-pipeline`
skill.

Paths below are the defaults. The live values come from the `paths:` block of
[.openspec/workflow.yaml](.openspec/workflow.yaml).

Windows and macOS: CLI `openspec` (npm); the gate is pure Python — `python3` on
macOS/Linux, `python` on Windows.

## The short path

1. **Explore the problem.** Use `/opsx:explore` to inspect the codebase and
   clarify the smallest useful scope.

2. **Complete S0 intake.** Write a non-empty `.pipeline/gap-report.md` before
   creating a change: what the codebase already covers, and what is missing.

3. **Create the change.**

   ```bash
   openspec new change fix-claim-status-transition
   ```

   Creates the folder with a `.openspec.yaml`. `/opsx:new` does this in Claude
   Code sessions.

4. **Author one artifact at a time** — proposal → delta specs → design → tasks,
   in order. `/opsx:continue` creates exactly the next ready artifact. Request
   its template first:

   ```bash
   openspec instructions proposal --change fix-claim-status-transition --json
   ```

   Fill `proposal.md`; repeat with `specs`, `design`, `tasks`.

5. **Validate**: `openspec validate --all`. Fix failures before proceeding.

6. **Run the gate.**

   ```bash
   python3 scripts/workflow_gate.py
   ```

   No `--stage` probes the first not-passing stage ("what's next");
   `--stage S1` / `domain-spec` checks one stage. Exit 0 = proceed, 1 = blocked.
   Line 1 is machine-readable: `GATE <S#> <stage-key> <STATE>`
   (DONE | READY | BLOCKED | ERROR). Hooks run it automatically; on demand
   always fine.

7. **Request review** only at the user-facing review gates: the combined S1+S2
   architecture review, the S3 plan review, and the S6 archive review. Record
   approval under `overrides:` with `key`, `after: approved`, `by`, and `when`
   (for example, `key: signoff.architecture`). S4 implementation and S5
   verification are automated checks, not user-facing review gates.

8. **Implement** — work `tasks.md` with TDD in an isolated worktree, with
   per-task commits. Your `coding_flow` sets the checkpoints inside this stage.

9. **Verify** — Stage 5 produces `.pipeline/verification-report.md` with
   per-criterion results; verify each criterion where practical. The gate
   enforces only ≥1 `- PASS` and 0 `- FAIL` lines; it does not establish that
   all criteria passed. `openspec status --change <name> --json` shows
   artifact-graph state anytime.

10. **Archive** — after archive sign-off and green validation:

    ```bash
    openspec archive <change> --yes
    ```

    Only after the archive succeeds, remove the transient reports:

    ```bash
    rm -f .pipeline/gap-report.md .pipeline/verification-report.md
    ```

    If the archive fails, leave the change and reports in place and report the
    failure. Sessions: `/opsx:archive`.

## Stages, gates, review

| Stage | Gate checks (artifacts) | Review |
|-------|-------------------------|--------|
| S0 intake | `.pipeline/gap-report.md` exists, non-empty | none |
| S1 domain-spec | proposal + specs done; KB validates when enabled | none — covered by the combined S1+S2 review |
| S2 architecture | design done; every delta spec references an ADR (`<adr_dir>/` or `ADR-<n>`); ≥1 ADR exists | human — combined S1+S2 |
| S3 tasks | `tasks.md` with anchored tasks (`Domain:`, `Rule:`, `ADR:`, `Tests:`, ...) | human |
| S4 implement | every task in `tasks.md` checked | automated |
| S5 verify | report with ≥1 `- PASS`, 0 `- FAIL` | automated |
| S6 archive | sign-off + `openspec validate` with 0 failed items | human |
| S7 compound | KB validates **and** the archived change is folded in (`scripts/kb_compound.py`), when enabled | none |

Defaults live in `.openspec/workflow.yaml`; per-change overrides in the change's
`.openspec.yaml`. Unrecorded overrides are rejected — the audit trail is never
bypassed, only the ceremony.

## The enforcement layer

Four levels: **L0** skills + pre-flight checks (read the gate's machine-readable
state) · **L1** the gate script, single source of truth for "may proceed" ·
**L2** git pre-commit (warn-only: *warn at git level, block at AI level*) ·
**L3** CI. Hooks in `.claude/settings.json` run the gate automatically; exit 1
**blocks the action** (`|| exit 2`) — including the Stop hook, so a turn cannot
end mid-stage:

| Hook event | Gate runs | Demands DONE |
|------------|-----------|--------------|
| Stop — every turn-end | bare run ("what's next") | the first stage not yet DONE |
| PreToolUse `openspec new change …` | S0 intake | gap report |
| PreToolUse `openspec instructions apply …` | S3 tasks | `tasks.md` anchored tasks |
| PreToolUse `openspec archive …` | S6 archive | sign-off + clean `openspec validate` |
| PreToolUse `openspec validate --specs …` | S5 verify | verification report (≥1 PASS, 0 FAIL) |
| PostToolUse `openspec-verify-change` / `/opsx:verify` | S4 implement | every task in `tasks.md` checked |

**Reading gate output.** Line 1: `GATE <S#> <stage-key> <STATE>` + `- ` reason
lines. States: `DONE` valid (+ recorded sign-off where required) · `READY` valid,
awaiting review/re-sign-off · `BLOCKED` missing/invalid artifact or upstream not
DONE (stages run in order — no skipping forward) · `ERROR` config/usage problem.
Read STATE from line 1; never append `; echo "exit=$?"` — it trips the
PreToolUse hooks' fail-open matcher.

**Idle tree:** nothing in flight ⇒ the bare gate reports `GATE idle`, exit 0 —
hooks and CI never block day-to-day work. **S0 admission** is enforced on the
explicit `--stage S0` path (what the PreToolUse hooks call before
`openspec new change`): missing ⇒
`GATE S0 intake BLOCKED: missing gap report`. A leftover verification report with
no workflow in progress blocks idle until cleaned up; a gap report alone does not
— it is S0's output, waiting for its change.

**Backward flow allowed; forward skipping not.** Revision is first-class
(`DONE → READY`, or `READY → BLOCKED` if an input was removed) and re-validates
only downstream artifacts. `/opsx:update` revises planning artifacts in any
direction; every revision is recorded — primary input to Stage 7 compound
learnings.

## Picking a coding flow

Three autonomy levels for Stage 4, picked **per change by judgment — there is no
automated risk classifier**.

| Flow | Checkpoints in Stage 4 | Use when |
|------|------------------------|----------|
| `standard` (default) | 1 — plan (tasks) review before coding | ordinary features |
| `validate` | 2 — design review + plan review before coding | security, payments, regulated data, core architecture |
| `autonomous` | 0 — code and test, straight through | bug fixes, trivial changes, low risk |

Set it in the change's `.openspec.yaml` (e.g. `coding_flow: validate`); default
from `.openspec/workflow.yaml`. All flows run identical verification and Stage 5
— **autonomy reduces review gates, never verification**. A mid-flight switch
takes effect only once recorded.

## Writing style

Keep prose terse: lead with the result, skip preamble and narration.

## Pointers

- **Setup and configuration:** [README.md](README.md)
- **Where does this repo stand?** `python3 scripts/harness_doctor.py` — what is
  set up, and which decisions are still open. Run it when a session starts in an
  unfamiliar repo, before assuming the harness is fully wired.
- **Slash commands:** `/opsx:new`, `/opsx:propose`, `/opsx:continue`,
  `/opsx:update`, `/opsx:apply`, `/opsx:verify`, `/opsx:sync`, `/opsx:archive`,
  `/opsx:bulk-archive`, `/opsx:explore`, `/opsx:ff`, `/opsx:onboard`.
  `/opsx:propose` + `/opsx:ff` are **discouraged** — author one artifact at a
  time by default; usable for small changes whose `.openspec.yaml` records a
  review-gate override.
- **Gate script:** `scripts/workflow_gate.py` — CLI contract in its docstring ·
  **hooks:** `.claude/settings.json` · **config:** `.openspec/workflow.yaml`
  (review policy, layout, coding-flow defaults, guardrails, override rules).
