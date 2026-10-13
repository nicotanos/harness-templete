---
type: ADR
title: "ADR-0001: Enforce the SDD pipeline with an artifact gate"
description: Why the SDD pipeline is enforced by a gate script rather than documented as guidance.
created_ts: 2026-08-28T00:00:00Z
authors: [human:nico]
status: stable
tags: [adr, pipeline]
---

# ADR-0001: Enforce the SDD pipeline with an artifact gate

## Status

Accepted

## Context

A spec-driven process that lives only in documentation is advisory. An agent
under time pressure — or a human in a hurry — skips the steps that feel like
ceremony, and the first casualty is always the same: the decisions nobody wrote
down. Review then happens against code, where changing course is expensive.

## Decision

Enforce the pipeline mechanically. Every stage names artifacts that must exist
and be valid on disk; `scripts/workflow_gate.py` is the single source of truth
for whether work may proceed, and Claude Code hooks run it automatically. A
blocked gate blocks the action, including turn-end.

Human review is reserved for three points — architecture (combined S1+S2), the
plan (S3), and archive (S6). Everything else is an artifact check.

## Consequences

- The pipeline cannot be skipped forward, only revised backward. Revision is a
  first-class transition that re-validates downstream artifacts alone.
- Policy overrides are allowed but take effect only once recorded. The ceremony
  is negotiable; the audit trail is not.
- The gate is a hard dependency: without PyYAML it cannot start, and hooks land
  in a half-broken state. `requirements.txt` is not optional.
- This ADR is the seed the template ships with, so Stage 2 has something to
  reference on day one. Replace or supplement it with your own decisions.
