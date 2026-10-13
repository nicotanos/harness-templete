---
name: brainstorming
description: "Use when collaborating with the engineer on the important decisions of an SDD Stage 1 (domain-spec: proposal, delta specs) or Stage 2 (architecture: design + ADRs) change — exploring intent, requirements, and design through dialogue before the planning artifacts are written. Use before authoring any planning artifact, whenever a decision materially affects scope, behavior, or architecture."
attribution: Adapted from superpowers (https://github.com/obra/superpowers)
---

# Brainstorming Ideas Into Designs

Turn a change idea into a fully formed design through collaborative dialogue with the engineer. In this pipeline the output is NOT a separate spec file — it IS the OpenSpec planning artifacts (S1: `proposal.md`, `specs/*.md`; S2: `design.md` + ADRs in the configured `adr_dir`). **The agent must not write those artifacts (or advance the pipeline) until the important decisions are made with the engineer.**

<HARD-GATE>
Do NOT author a planning artifact, invoke an implementation skill, or advance the pipeline until you have presented the design and the engineer has approved it — regardless of perceived simplicity.
</HARD-GATE>

**Anti-pattern: "too simple for a design."** Every change goes through this. Simple changes are where unexamined assumptions cost most; the design may be short (a few sentences), but you MUST present it, get approval, and record decisions in the artifacts.

## When to Use

- S1 domain-spec: before `proposal.md` / `specs/*.md` — clarify intent, scope, domain model, acceptance criteria
- S2 architecture: before `design.md` + ADRs (the configured `adr_dir`) — derive service boundaries, event contracts, infra from the domain model; get sign-off
- Any point where a question materially affects scope, externally observable behavior, compatibility, or acceptance criteria

The dialogue drives the artifacts: the conversation's outcome IS the proposal/specs/design/ADR content. Never record a decision the engineer has not made.

## Checklist (create a task per item; complete in order)

1. **Explore project context** — the gap report, existing specs and ADRs, recent commits
2. **Clarify the change in one planning conversation** — ask focused questions one at a time, covering purpose, scope, success criteria, domain concepts, and architectural constraints
3. **Propose 2-3 approaches** — trade-offs + your recommendation (lead with it)
4. **Present and refine the design** — cover the S1 domain decision and the S2 architecture in one continuous conversation; preserve the distinction between domain-driven design (proposal, delta specs, and domain model) and architecture decisions (design and ADRs)
5. **Write the OpenSpec artifacts** — only after the engineer approves the direction: S1 proposal and delta specs; then S2 design and ADRs, all reflecting the same approved decisions
6. **Artifact self-review** — placeholders, contradictions, ambiguity, scope (below); fix inline
7. **Combined S1+S2 review** — once all planning artifacts are ready, review proposal, specs, design, and ADRs together; revise until approved
8. **Transition to Stage 3** — after the combined review is approved, invoke `writing-plans`.

Flow: 1→2→3→4 →(single approval)→ 5→6→7 →(combined review approval)→ 8.

**Terminal state:** invoke `writing-plans` after the combined review approval. Do NOT invoke any implementation skill (TDD, subagent-driven-development, …) from here — those are Stage 4. The ONLY next skill is writing-plans.

## The Process

**Understanding the idea**
- Check project state first (gap report, existing specs and ADRs, recent commits)
- Assess scope BEFORE detailed questions: multiple independent subsystems ⇒ flag immediately — this pipeline creates **one change folder per feature**; don't refine details of a bundle needing decomposition
- Otherwise ask questions one at a time; multiple-choice preferred, open-ended fine; focus on purpose, constraints, success criteria

**Exploring approaches** — propose 2-3 with trade-offs, conversationally, recommendation first.

**Presenting the design** — when you understand what's being built, present the S1 domain model and S2 architecture as one connected design discussion. Cover architecture/components, data flow, error handling, and testing at a depth suited to the change; invite corrections and resolve open decisions in the conversation rather than seeking section-by-section approval.

## After the Design

**Documentation** — write the validated design into the OpenSpec planning artifacts via the `openspec` CLI (NOT a `docs/superpowers/specs/` file):
- S1: `openspec instructions proposal --change "<name>" --json` → `proposal.md`; `openspec instructions specs --change "<name>" --json` → delta specs `specs/<capability-path>/spec.md`
- S2: `openspec instructions design --change "<name>" --json` → `design.md` (Stage 2 output, not Stage 1); ADRs as `<adr_dir>/ADR-<n>.md`
Follow artifact templates + the spec-quality/collaboration rules in `openspec/config.yaml` (surfaced by `openspec instructions`).

**Self-review** (fix inline, no re-review): placeholder scan (TBD/TODO/vague) · internal consistency across artifacts · scope fits ONE change folder? · Binary Test — could two agents disagree on a criterion passing? Then pick one interpretation, make it explicit.

**Engineer review gate**: after self-review, ask (e.g. "Artifacts for change `<name>` are ready for the combined S1+S2 review (proposal, specs, design, ADRs). Please review them together before we write the implementation plan."), then address the engineer's feedback. Changes requested → make them, re-run self-review. Proceed to `writing-plans` immediately after approval.

One question at a time · multiple choice preferred · YAGNI ruthlessly · always 2-3 approaches · connected S1→S2 reasoning · **the engineer decides** — the single planning approval and combined artifact review are human gates; the dialogue is how you earn sign-off, not a formality.
