---
name: writing-plans
description: Use when writing the Stage 3 implementation plan for an OpenSpec change  — turning an approved change (proposal + delta specs + design + ADRs, after the combined S1+S2 review) into a bite-sized, dependency-ordered `tasks.md` with anchored tasks. Use when a change's tasks need to be specific enough for a fresh coding agent to execute without asking.
attribution: Adapted from superpowers (https://github.com/obra/superpowers)
---

# Writing Plans

Write `tasks.md` for an executing agent with little codebase context. Keep each
task independently understandable and tied to the approved specs and design.
Describe dependencies, interfaces, invariants, failure modes, and the tests
that prove them. Use concise technical prose; include only critical snippets.

> Write only after the combined S1+S2 architecture review is approved.

Announce: "I'm using the writing-plans skill to write the implementation plan."

Save to the `resolvedOutputPath` returned by `openspec instructions tasks`.

## Scope and granularity

Split independent subsystems during S1/S2. Each task is one focused change in
dependency order. Name the exact files and symbols involved and follow existing
repository patterns. Prefer a small number of complete, testable tasks over a
large checklist.


Use one `- [ ]` checkbox per task. Within each task block (from its checkbox
until the next task checkbox), include at least one non-empty anchor bullet that
applies to the task; anchors may appear anywhere in the block.
Anchor bullets name exact domain, event, rule, ADR, infrastructure, or test
references when applicable; do not add inapplicable categories just to fill out
a template. Use bold prose steps, not nested checkboxes.

```markdown
- [ ] Implement ClaimSubmissionService.Validate()
  - Domain: billing/claim
  - Event contract: ClaimSubmitted (schema v1)
  - Rule: RCM-R7 timely filing <= 90 days
  - ADR: 0014
  - Infra: PHI firewall zone 1
  - Tests: tests/billing/claim/test_validation.py

  **Step 1: Add the failing test for an in-window claim.**

  **Step 2: Implement the smallest behavior satisfying the criterion.**

  **Step 3: Add boundary and failure-mode coverage.**
```

Code snippets are limited to critical interfaces or assertions. Do not include
comprehensive implementations, shell commands, expected command output, or
commit instructions. The anchor block must use exact references from the
approved delta specs and design.

## No placeholders

Do not write TBD, TODO, implement later, vague error-handling directives, or
references to undefined types and functions. State concrete behavior and tests.

## Self-review

Check that every requirement maps to a task, dependencies and names agree with
the specs, no placeholders remain, and every task block contains at least one non-empty applicable anchor.

## Execution handoff

After saving `tasks.md`, continue with the implementation workflow. The plan is
an execution input, not a second requirements document.
