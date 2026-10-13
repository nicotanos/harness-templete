#!/usr/bin/env python3
"""kb_validate.py — Open Knowledge Format (OKF) v0.2 conformance validator.

Optional component of the SDD harness. The gate runs it for stages S1 and S7
only when `kb.enabled: true` in .openspec/workflow.yaml.

Usage: python3 scripts/kb_validate.py [directory] [--quiet] [--strict]
       Defaults to docs/. --quiet prints nothing when all checks pass.
       --strict promotes every WARN to an ERROR.

Conformance (OKF v0.2, "Conformance Requirements")
--------------------------------------------------
A bundle conforms when:

  1. every non-reserved `.md` file carries parseable YAML frontmatter, and
  2. that frontmatter has a non-empty `type`.

Reserved filenames (`index.md`, `log.md`) carry optional frontmatter only and
are exempt from the `type` requirement.

The spec is explicit that a consumer MUST NOT reject a bundle for missing
optional fields, unknown types, unknown keys, broken links, or absent
indexes. This validator honours that: only the two rules above are ERRORs.
Everything else is a WARN — advisory signal, never a gate.

Exit code: 0 when no ERROR (PASSED), 1 otherwise (FAILED). Warnings do not
affect the exit code unless --strict is given.
"""

import argparse
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    import yaml
except ImportError:
    print(
        "ERROR: PyYAML is required. Install the harness dependencies with:\n"
        "    python3 -m pip install -r requirements.txt",
        file=sys.stderr,
    )
    sys.exit(1)


class _NoTimestampLoader(yaml.SafeLoader):
    """SafeLoader that keeps timestamp-looking scalars as plain strings.

    PyYAML's default resolver silently converts unquoted ISO datetimes
    (`created_ts: 2026-08-05T10:00:00Z`) into datetime objects, which breaks
    round-tripping and the ISO 8601 checks below."""


_NoTimestampLoader.yaml_implicit_resolvers = {
    ch: [(tag, rx) for tag, rx in resolvers if tag != "tag:yaml.org,2002:timestamp"]
    for ch, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}

RESERVED = {"index.md", "log.md"}
STATUSES = {"draft", "stable", "deprecated"}
# OKF actor convention: human:<id> | <producer>/<version> | process:<id>
ACTOR_RE = re.compile(r"^(human:[^\s]+|process:[^\s]+|[^\s/]+/[^\s]+)$")
FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*(?:\n|\Z)", re.DOTALL)
# Datetime fields carrying an ISO 8601 instant.
TIME_FIELDS = ("created_ts", "modified_ts", "stale_after", "last_modified")


class Report:
    def __init__(self, strict=False):
        self.errors = []
        self.warns = []
        self.strict = strict

    def error(self, where, message):
        self.errors.append(f"ERROR: {where}: {message}")

    def warn(self, where, message):
        target = self.errors if self.strict else self.warns
        prefix = "ERROR" if self.strict else "WARN"
        target.append(f"{prefix}: {where}: {message}")


def parse_frontmatter(text):
    """(data, error). data is None when there is no frontmatter block."""
    match = FRONTMATTER_RE.match(text)
    if not match:
        return None, None
    try:
        data = yaml.load(match.group(1), Loader=_NoTimestampLoader)
    except yaml.YAMLError as exc:
        return None, f"unparseable YAML frontmatter ({exc.__class__.__name__})"
    if data is None:
        return {}, None
    if not isinstance(data, dict):
        return None, "frontmatter must be a YAML mapping"
    return data, None


def _iso(value):
    """True when value parses as an ISO 8601 datetime (Z suffix allowed)."""
    if not isinstance(value, str):
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        return True
    except ValueError:
        return False


def check_actor(report, where, field, value):
    for actor in value if isinstance(value, list) else [value]:
        if isinstance(actor, str) and not ACTOR_RE.match(actor):
            report.warn(
                where,
                f"{field}: {actor!r} does not follow the OKF actor convention "
                f"(human:<id>, <producer>/<version>, or process:<id>)",
            )


def check_event(report, where, field, value):
    """`generated` / `verified` entries: { by, at }."""
    entries = value if isinstance(value, list) else [value]
    for entry in entries:
        if not isinstance(entry, dict):
            report.warn(where, f"{field}: entry is not a mapping with 'by' and 'at'")
            continue
        for key in ("by", "at"):
            if not entry.get(key):
                report.warn(where, f"{field}: entry is missing {key!r}")
        if "by" in entry:
            check_actor(report, where, f"{field}.by", entry["by"])
        if "at" in entry and not _iso(entry["at"]):
            report.warn(where, f"{field}.at: {entry['at']!r} is not an ISO 8601 datetime")


def check_document(report, path, root):
    where = str(path.relative_to(root))
    text = path.read_text(encoding="utf-8", errors="replace")
    data, error = parse_frontmatter(text)
    reserved = path.name in RESERVED

    if error:
        report.error(where, error)
        return
    if data is None:
        # Reserved files carry OPTIONAL frontmatter; concepts require it.
        if not reserved:
            report.error(where, "missing YAML frontmatter (OKF requires a frontmatter block)")
        return
    if reserved:
        return  # optional frontmatter only; no type requirement

    kind = data.get("type")
    if not isinstance(kind, str) or not kind.strip():
        report.error(where, "frontmatter has no non-empty 'type' (the only required OKF field)")

    # ---- advisory signals below: never a gate ----
    for field in ("title", "description"):
        if not data.get(field):
            report.warn(where, f"missing {field!r} (recommended)")
    for field in TIME_FIELDS:
        if field in data and not _iso(data[field]):
            report.warn(where, f"{field}: {data[field]!r} is not an ISO 8601 datetime")
    if "authors" in data:
        check_actor(report, where, "authors", data["authors"])
    for field in ("generated", "verified"):
        if field in data:
            check_event(report, where, field, data[field])
    status = data.get("status")
    if status is not None and status not in STATUSES:
        report.warn(where, f"status: {status!r} is not one of {sorted(STATUSES)}")
    stale = data.get("stale_after")
    if _iso(stale):
        when = datetime.fromisoformat(stale.replace("Z", "+00:00"))
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) >= when:
            report.warn(where, f"content is stale (stale_after {stale} has passed)")
    sources = data.get("sources")
    if sources is not None:
        if not isinstance(sources, list):
            report.warn(where, "sources: expected a list of entries")
        else:
            for i, entry in enumerate(sources):
                if not isinstance(entry, dict) or not entry.get("resource"):
                    report.warn(where, f"sources[{i}]: every entry needs a 'resource'")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Validate an OKF v0.2 knowledge bundle")
    parser.add_argument("directory", nargs="?", default="docs", help="bundle root (default: docs)")
    parser.add_argument("--quiet", action="store_true", help="print nothing when all checks pass")
    parser.add_argument("--strict", action="store_true", help="treat warnings as errors")
    args = parser.parse_args(argv)

    root = Path(args.directory)
    if not root.is_dir():
        print(f"ERROR: not a directory: {root}", file=sys.stderr)
        return 1

    report = Report(strict=args.strict)
    # Hidden-path check is relative to the bundle root: an absolute or
    # `../`-prefixed root would otherwise exclude every document.
    documents = sorted(
        p for p in root.rglob("*.md")
        if not any(part.startswith(".") for part in p.relative_to(root).parts)
    )
    for path in documents:
        check_document(report, path, root)

    for line in report.warns:
        print(line)
    for line in report.errors:
        print(line)

    if report.errors:
        print(f"\nFAILED: {len(report.errors)} error(s), {len(report.warns)} warning(s) "
              f"across {len(documents)} document(s)")
        return 1
    if not args.quiet:
        print(f"PASSED: {len(documents)} document(s), {len(report.warns)} warning(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
