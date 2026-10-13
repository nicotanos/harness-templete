# SDD Harness

A template repo for artifact-enforced, spec-driven development with Claude Code.

Every change moves through eight stages (S0–S7). Each stage requires named
artifacts on disk, and a gate script decides whether work may proceed. Claude
Code hooks run the gate automatically, so the rules bind the agent rather than
relying on its goodwill — a blocked gate blocks the action, including turn-end.

Project-agnostic by construction: no knowledge base required, every path
configurable, no assumptions about your language, framework, or layout.

## Start here

You made a repo from this template. Six commands, then the harness tells you
what is left:

```bash
python3 -m pip install -r requirements.txt
npm install -g @fission-ai/openspec
openspec config profile          # choose: custom, all 12 workflows
openspec update                  # generates the /opsx:* commands

python3 -m pytest scripts/tests -q      # 144 passed = the install is sound
python3 scripts/harness_doctor.py       # what is set up, what is still yours
```

The doctor is the answer to "what do I still have to do". It separates two
things a checklist in a README never can:

```
[ TODO ] /opsx: commands    openspec update  (the template does not vendor them)
[yours ] ADRs               only the seed ADR — record your own decisions
[yours ] README             still describes the harness — replace it
[  ok  ] gate               GATE idle: no workflow in progress
```

`TODO` means the harness does not work yet and the exit code says so. `yours`
means a decision nobody has made — never a failure, and some stay open for a
long time. Re-run it whenever you wonder where you are.

It is deliberately not part of CI. It reports on a workspace — an installed git
hook, generated commands, a README someone still has to write — and CI has no
workspace. The tests already catch a broken install; adding the doctor there
would only produce failures nobody can act on.

### What the template deliberately leaves blank

| | Why it is yours |
|---|---|
| `README.md` | This file describes the harness. Yours describes your project. |
| `LICENSE` | The template's MIT does not carry over to your code. |
| ADRs beyond the seed | Your stack, your constraints. See `templates/adr.md`. |
| `kb.enabled` | Off by default. Turn it on when knowledge starts repeating. |
| The `paths:` block | Defaults suit most repos; change them if yours differs. |
| CI | Copy the GitHub workflow or the GitLab example, not both. |

### Your first change

Stage 0 comes before the change folder exists:

```bash
mkdir -p .pipeline && cp templates/gap-report.md .pipeline/gap-report.md
$EDITOR .pipeline/gap-report.md          # what exists, what is missing
openspec new change <short-name>
```

From there `python3 scripts/workflow_gate.py` answers "what's next" at every
point, and the hooks block anything that skips ahead. Make the first change the
thinnest slice that works end to end — the pipeline cannot tell an honest scope
from an ambitious one, and that judgement stays yours.

## Two ways to use it

**Start a new project from it.** Use this repo as a template (or clone it), then
build your project inside. Everything is already wired; delete what you do not
want.

**Add it to an existing repo.** Copy the harness files listed below into your
repo root and merge `.claude/settings.json` by hand. See *Install into an
existing repo*.

## What's in the box

| Path | Role | Required |
|---|---|---|
| `scripts/workflow_gate.py` | The gate. Single source of truth for "may proceed" | yes |
| `scripts/hook_gate.py` | Deterministic PreToolUse trigger | yes |
| `.openspec/workflow.yaml` | Review policy, repo layout, coding flows | yes |
| `.claude/settings.json` | The hooks that enforce the gate | yes |
| `openspec/config.yaml` | Per-artifact authoring rules | yes |
| `requirements.txt` | Python dependencies | yes |
| `scripts/tests/` | 144 tests — also your install check | recommended |
| `scripts/kb_validate.py` | OKF v0.2 knowledge-base validator | optional |
| `scripts/kb_compound.py` | Stage 7: folds an archived change into the KB | optional |
| `scripts/harness_doctor.py` | Reports setup state and open decisions | recommended |
| `.claude/skills/` | `sdd-pipeline`, `brainstorming`, `writing-plans` | recommended |
| `CLAUDE.md` | The operating manual the agent reads each session | recommended |
| `templates/` | Starting points for the two transient reports | optional |
| `docs/adr/ADR-0001-*.md` | Seed ADR — Stage 2 needs at least one | recommended |
| `.github/workflows/sdd.yml`, `ci/gitlab-ci.example.yml` | CI | optional |
| `scripts/pre-commit` | Git hook, warn-only | optional |

## Prerequisites

```bash
npm install -g @fission-ai/openspec        # >= 1.9.0
openspec config profile                     # choose: custom, all 12 workflows
python3 -m pip install -r requirements.txt  # PyYAML
```

The profile matters. A narrower one makes `openspec update` silently drop the
expanded commands (`new`, `continue`, `ff`, `verify`, `bulk-archive`,
`onboard`).

**The `/opsx:*` commands and `openspec-*` skills are not in this repo on
purpose.** `openspec update` generates them, so a vendored copy only goes stale.
Run it once after installing:

```bash
openspec update
```

The pipeline's own rules live in `openspec/config.yaml`, which `openspec update`
does **not** touch — that is why the review boundaries are written there rather
than appended to the generated command files.

Three skills ship here because they are specific to this pipeline:
`sdd-pipeline`, `brainstorming`, `writing-plans`. They reference general-purpose
skills — `test-driven-development`, `using-git-worktrees`,
`subagent-driven-development`, `requesting-code-review`, `stop-slop` — which are
**not** vendored. `.claude/settings.json` requests the
[superpowers](https://github.com/obra/superpowers) plugin via `enabledPlugins`,
so a session opened in this repo is prompted to enable it; installing it once at
user scope covers every project. Drop the entry — and the references in the
skills — if you would rather not. The pipeline works without them: you lose the
implementation discipline they carry, not the gate.

## Install into an existing repo

From your repo root, with this template checked out at `$T`:

```bash
cp -R $T/scripts $T/.openspec $T/templates .
cp $T/requirements.txt $T/CLAUDE.md .
mkdir -p openspec && cp $T/openspec/config.yaml openspec/
mkdir -p docs/adr && cp $T/docs/adr/ADR-0001-*.md docs/adr/
cat $T/.gitignore >> .gitignore

# Hooks and skills: merge if .claude already exists, copy if not.
mkdir -p .claude && cp -R $T/.claude/skills .claude/
cp $T/.claude/settings.json .claude/      # MERGE the "hooks" block if you have one

# CI: pick one
cp $T/.github/workflows/sdd.yml .github/workflows/
cp $T/ci/gitlab-ci.example.yml ci/
```

Copy `scripts/` **without** `__pycache__`. Seed at least one ADR before starting
— Stage 2 requires a file in `paths.adr_dir`, so an empty directory blocks every
change. The shipped `ADR-0001` covers that and documents why the pipeline is
enforced; replace it with your own decisions as they accumulate.

Optional git hook (warn-only; the real block is L1):

```bash
cp scripts/pre-commit .git/hooks/ && chmod +x .git/hooks/pre-commit
```

## Verify the install

```bash
python3 -m pytest scripts/tests -q      # expect 144 passed
python3 scripts/harness_doctor.py       # setup state and open decisions
python3 scripts/workflow_gate.py        # expect: GATE idle
```

`GATE idle: no workflow in progress — Stage 0 starts a change` is the correct
first result: the harness is installed and nothing is in flight. It stays idle
(exit 0) until you start a change, so CI on a new project is green from day one.

S0 admission is still enforced where it matters — `openspec new change` runs the
gate as `--stage S0` and blocks until `.pipeline/gap-report.md` exists. Start
from `templates/gap-report.md`.

The test suite reads its layout from `.openspec/workflow.yaml`, so it stays
green after you customise `paths:`. If it fails, your install is wrong — not
your configuration.

## Configuration

Everything lives in `.openspec/workflow.yaml`.

**Layout.** Every path the gate touches:

```yaml
paths:
  pipeline_dir: .pipeline          # transient stage reports
  gap_report: gap-report.md
  verification_report: verification-report.md
  changes_dir: openspec/changes    # archive is <changes_dir>/archive
  adr_dir: docs/adr                # Stage 2 requires >= 1 file here
```

**Knowledge base.** Off by default; S1 and S7 then check artifacts alone.

```yaml
kb:
  enabled: false
  root: docs
  validator: scripts/kb_validate.py
```

Turning it on adds the validator to S1 (new pages) and S7 (whole bundle), and
makes S7 additionally require that the archived change has been folded in — see
*Compounding* below.

**Turning it on with `root: docs` means your ADRs become KB documents**, so they
need OKF frontmatter (`type`, `title`, `created_ts`, `authors`). That is the
right outcome — an ADR is durable knowledge — and `templates/adr.md` ships with
the frontmatter already in place. Without it, S1 and S7 fail on the ADR
directory.
The shipped validator implements Open Knowledge Format v0.2: a directory of
Markdown files with YAML frontmatter, where only `type` is required. It fails
a bundle only for missing/unparseable frontmatter or a missing `type` — the
spec forbids rejecting for unknown types, unknown keys, broken links, or absent
indexes. Everything else is a warning. Use `--strict` to promote warnings.
Point `validator` at your own script if you prefer; the gate only reads its
exit code.

### Compounding (Stage 7)

`scripts/kb_compound.py` turns an archived change into knowledge-base
scaffolding:

```bash
python3 scripts/kb_compound.py            # write log entry, stubs, index
python3 scripts/kb_compound.py --check    # what is still pending (exit 1)
```

It writes `<kb.root>/log.md` (one idempotent entry per archived change, with the
capabilities, the ADRs, and who approved what), a capability page per capability
the change touched, and a regenerated `index.md`.

It deliberately does **not** write the body of a capability page. The canonical
behaviour already lives in `openspec/specs/**`; copying it into the KB produces
a second copy that drifts. The stub carries frontmatter, provenance, and links,
and leaves a marker where the *why* goes — what the capability is for, what
building it taught you, what would surprise a newcomer reading the spec cold.

S7 blocks while that marker is still there. Scaffolding is not compounding: a
knowledge base of empty stubs is the spec index this design exists to avoid.
Existing pages are never overwritten.

**Review policy.** Per stage, one of `none` / `human` / `agent`:

```yaml
stages:
  architecture: { review: human }
```

`archive` may never be `none` — that guardrail is enforced.

**Coding flow.** Stage 4 autonomy, chosen per change by judgment:

| Flow | Checkpoints | Use when |
|---|---|---|
| `autonomous` | 0 | bug fixes, trivial changes |
| `standard` | 1 — plan review | ordinary features (default) |
| `validate` | 2 — design + plan review | security, payments, regulated data, core architecture |

All three run identical verification. Autonomy reduces review gates, never
verification.

**Per-change overrides** go in `<changes_dir>/<name>/.openspec.yaml` and take
effect only once recorded. The ceremony is negotiable; the audit trail is not.

## The stages

| Stage | Gate checks | Review |
|---|---|---|
| S0 intake | gap report exists, non-empty | — |
| S1 domain-spec | proposal + specs done (+ KB if enabled) | — |
| S2 architecture | design done; every delta spec cites an ADR; ≥1 ADR exists | human |
| S3 tasks | `tasks.md` with anchored tasks | human |
| S4 implement | `openspec status` complete | automated |
| S5 verify | report with ≥1 `- PASS`, 0 `- FAIL` | automated |
| S6 archive | sign-off + `openspec validate` clean | human |
| S7 compound | KB validates (no-op when disabled) | — |

Anchored tasks carry at least one bullet from `Domain:` / `Event contract:` /
`Rule:` / `ADR:` / `Infra:` / `Tests:`.

Sign-offs are recorded under `overrides:` in the change's `.openspec.yaml`:

```yaml
overrides:
  - key: signoff.architecture
    after: approved
    by: nico
    when: 2026-08-28
```

## Reading gate output

Line 1 is machine-readable: `GATE <S#> <stage-key> <STATE>`, then `- ` reasons.

- **DONE** — valid, and signed off where required. Exit 0.
- **READY** — artifacts valid, awaiting review. Exit 1.
- **BLOCKED** — missing/invalid artifact, or an upstream stage is not DONE.
- **ERROR** — config or usage problem.

Never append `; echo "exit=$?"` to a gate command — it trips the PreToolUse
hooks' fail-open matcher.

**Idle tree.** With no change in flight the gate reports `GATE idle` and exits
0, so hooks and CI never block day-to-day work. S0 admission lives on the
explicit `--stage S0` path the PreToolUse hooks call, not on the bare run — that
is what blocks `openspec new change` until a gap report exists. A leftover
verification report with no workflow in progress blocks idle until cleaned up; a
gap report alone does not, since it is S0's output waiting for its change.

**Backward flow.** Revision is first-class: `DONE → READY` re-validates only
downstream artifacts. Gates prevent skipping forward, never revisiting.

## A change, end to end

```bash
# S0 — write .pipeline/gap-report.md first, then:
openspec new change add-greeting-flag
# S1/S2 — author proposal, specs, design; add an ADR
openspec instructions proposal --change add-greeting-flag --json
# record signoff.architecture, then S3
openspec instructions tasks --change add-greeting-flag --json
# record signoff.tasks, then implement, then write the S5 report
python3 scripts/workflow_gate.py            # what's next, any time
# record signoff.archive, then:
openspec archive add-greeting-flag --yes
rm -f .pipeline/gap-report.md .pipeline/verification-report.md
```

Remove the transient reports only **after** the archive succeeds. If it fails,
leave everything in place.

## Known constraints

- **PyYAML is not optional.** Without it the gate cannot start: PreToolUse
  hooks fail closed and the Stop hook fails open — a half-broken state that
  looks like a harness bug. Install `requirements.txt` in CI too.
- **`operations.*.guidance` in `openspec/config.yaml` must be a list of
  strings.** OpenSpec ignores a block scalar there and only whispers about it.
- **Hook matchers are best-effort.** Claude Code's `if: "Bash(...)"` filter
  fails open on commands containing `$()`, backticks, or variables, which is
  why `hook_gate.py` re-checks the command itself. Keep both.
- **One active change at a time**, unless you pass `--change`. With no active
  change, the most recently archived one is resolved.
- **`openspec update` regenerates the workflow commands and drops anything
  appended to them.** Keep project rules in `openspec/config.yaml`.
- **The gate does not check that you verified every criterion.** S5 enforces
  ≥1 PASS and 0 FAIL. Covering the whole spec is a discipline the gate cannot
  see — `templates/verification-report.md` says so out loud.

## License

MIT — see [LICENSE](LICENSE). Copy what you need into your own repo; keep the
notice with substantial portions.

The `brainstorming` skill is adapted from
[superpowers](https://github.com/obra/superpowers), as noted in its frontmatter.
