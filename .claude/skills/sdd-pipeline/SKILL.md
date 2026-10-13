---
name: sdd-pipeline
description: Operate the artifact-enforced SDD pipeline and advance a change one outcome at a time.
---

# SDD pipeline (S0–S7)

OpenSpec artifacts and status remain the source of truth for feature intent and
its proposal → specs/design → tasks → implementation DAG. The gate adds the
checks below. After each successful stage, continue with the next listed action.

Paths named here are the defaults; the live values come from the `paths:` block
of `.openspec/workflow.yaml`.

| Stage | Outcome | Gate | Review |
|---|---|---|---|
| S0 intake | `.pipeline/gap-report.md` records known and missing concepts | gap report exists and is non-empty | automated |
| S1 domain-spec | engineer-approved proposal and delta specs | proposal and specs are complete; KB validation passes when enabled | combined with S2 |
| S2 architecture | `design.md`, durable ADRs, and ADR references in each delta spec | design and ADRs exist; every delta spec references an ADR | human, combined S1/S2 |
| S3 tasks | anchored, dependency-ordered `tasks.md` | tasks exist and each task has an applicable anchor | human |
| S4 implement | implementation complete; tests are required by implementation practice; commit after each task | `openspec instructions apply --change <name> --json` reports `progress.remaining: 0` | automated |
| S5 verify | `.pipeline/verification-report.md` records per-criterion results; verify each criterion where practical | report has at least one PASS and no FAIL | automated |
| S6 archive | archived change; transient reports cleaned after successful archive execution | archive prerequisites, `openspec validate <change>`, and review pass; movement and cleanup occur only after archive execution succeeds | human |
| S7 compound | reusable learnings recorded; the archived change folded into the KB | KB validation passes and `kb_compound.py --check` is clean, when enabled | automated |

## Actions

- Start with S0 discovery, then create one OpenSpec change per feature.
- Before S1/S2 artifacts, use `brainstorming` to settle scope, domain decisions,
  boundaries, contracts, and acceptance criteria with the engineer. Do not make
  a second artifact walk: review S1 and S2 together when design and ADRs exist.
- Write S3 with `writing-plans`: concise technical prose covering dependencies,
  interfaces, invariants, failure modes, and tests. Include only critical
  snippets; omit comprehensive code, shell commands, expected output, and commit
  directions. Every task block (from its checkbox until the next task checkbox)
  has at least one non-empty applicable anchor from
  Domain/Event contract/Rule/ADR/Infra/Tests; the anchor may appear anywhere in
  that block.
- Implement with `openspec-apply-change`, TDD, isolated worktrees, and focused
  review discipline. Commit each task once its tests pass; never batch tasks into
  one commit. Verification is required regardless of coding flow.
- Where practical, verify each delta-spec criterion and record its result in the
  verification report, then archive only after the archive review and validation
  pass.

## Gate

Gate predicates are distinct from implementation guidance. S4 checks only that
OpenSpec reports a complete change; passing tests remain required by
implementation practice. S6 checks archive prerequisites, validation, and review;
movement and transient-report cleanup happen only after archive execution
succeeds. A leftover verification report with no workflow in progress blocks the
idle gate — clean it before starting intake.

Run the gate any time to see what is next:

```bash
python3 scripts/workflow_gate.py                    # what's next
python3 scripts/workflow_gate.py --stage S2         # one stage
```

Read the state from line 1 (`GATE <S#> <stage-key> <STATE>`). Never append
`; echo "exit=$?"` — it trips the PreToolUse hooks' fail-open matcher.

## Stage 7 compounding

When the knowledge base is enabled, run `python3 scripts/kb_compound.py` after
archiving. It writes the log entry, a capability stub per capability, and the
index — then **you** write the why in each stub and delete the `kb_compound`
marker. S7 stays BLOCKED until you do. Do not restate the spec: the canonical
behaviour is already in `openspec/specs/**`; the page is for what the spec
cannot say.

## Recording sign-off

Stages whose review is `human` or `agent` need an approved record under
`overrides:` in the change's `.openspec.yaml`:

```yaml
overrides:
  - key: signoff.architecture
    after: approved
    by: <who>
    when: 2026-08-28
```

Keys are `signoff.<stage-key>`. Records are append-only; the latest wins.
An override that is not recorded is rejected — the audit trail is never
bypassed, only the ceremony.
