#!/usr/bin/env python3
"""kb_compound.py — Stage 7 (compound): fold an archived change into the KB.

Optional component, paired with scripts/kb_validate.py. Runs only when
`kb.enabled: true` in .openspec/workflow.yaml; otherwise it is a no-op.

Usage: python3 scripts/kb_compound.py [--change NAME] [--check] [--repo ROOT]

    --change  archived change to fold in (default: the most recent one).
    --check   report what is still pending and exit 1 instead of writing.
    --repo    repo root (default: parent of this script's directory).

What it writes
--------------
    <kb.root>/log.md                    one entry per archived change
    <kb.root>/capabilities/<cap>.md     a stub per capability the change touched
    <kb.root>/index.md                  regenerated from the tree

What it deliberately does NOT write
-----------------------------------
The body of a capability page. The canonical behaviour already lives in
openspec/specs/**; copying it into the KB produces a second copy that drifts.
The stub carries frontmatter, provenance, and links, and leaves a marker where
the *why* goes — what the capability is for, what building it taught us, what
would surprise a newcomer. A human or an agent writes that in Stage 7.

`--check` reports three kinds of pending work, and the S7 gate blocks on all
three: a missing log entry, a missing capability stub, and a stub whose body
still carries the marker.

Exit codes: 0 nothing pending (or written successfully), 1 pending/error.
"""

import argparse
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from workflow_gate import (  # noqa: E402  — same directory, shared config layer
    GateError,
    _read_yaml,
    archive_dir,
    kb_of,
    list_archived_changes,
    load_workflow,
)

REPO_ROOT = SCRIPT_DIR.parent
PRODUCER = "kb_compound/1.0"

# The marker that means "the why is still unwritten". Its presence is the
# single, unambiguous signal --check keys on.
MARKER = "<!-- kb_compound:"
STUB_BODY = """<!-- kb_compound: write the WHY here, then delete this comment.

     What does this capability exist for? What did building it teach us? What
     would surprise someone reading the spec cold? The canonical behaviour is
     in the spec linked above — do not restate it here. -->
"""

ADR_RE = re.compile(r"ADR[-\s]?(\d{1,4})", re.IGNORECASE)
LOG_ENTRY_RE = re.compile(r"^### (?P<change>\S+)", re.MULTILINE)
ARCHIVE_DIR_RE = re.compile(r"^(?P<date>\d{4}-\d{2}-\d{2})-(?P<name>.+)$")


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _title(slug):
    return slug.replace("-", " ").replace("_", " ").strip().capitalize()


def resolve_archive(root, cfg, change=None):
    """(path, name, date) of the archived change folder to fold in."""
    base = root / archive_dir(cfg)
    if not base.is_dir():
        raise GateError(f"no archive directory: {archive_dir(cfg)}")
    if change is None:
        names = list_archived_changes(root, cfg)
        if not names:
            raise GateError("no archived change to compound")
        change = names[-1]  # date-sorted; the most recent
    for folder in sorted(base.iterdir()):
        m = ARCHIVE_DIR_RE.fullmatch(folder.name)
        if m and m.group("name") == change and (folder / ".openspec.yaml").is_file():
            return folder, change, m.group("date")
    raise GateError(f"archived change not found: {change!r}")


def capabilities_of(archive_path):
    """Capability slugs the change touched, from its delta spec paths."""
    specs = archive_path / "specs"
    if not specs.is_dir():
        return []
    found = set()
    for spec in specs.rglob("*.md"):
        rel = spec.relative_to(specs)
        # specs/<capability>/spec.md, or specs/<capability>.md
        found.add(rel.parts[0][:-3] if len(rel.parts) == 1 else rel.parts[0])
    return sorted(found)


def adrs_of(archive_path):
    """ADR numbers referenced by the change's delta specs and design."""
    found = set()
    sources = list((archive_path / "specs").rglob("*.md")) if (archive_path / "specs").is_dir() else []
    design = archive_path / "design.md"
    if design.is_file():
        sources.append(design)
    for path in sources:
        for num in ADR_RE.findall(path.read_text(encoding="utf-8", errors="replace")):
            found.add(f"ADR-{int(num):04d}")
    return sorted(found)


def signoffs_of(archive_path):
    """[(stage, by, when)] from the archived .openspec.yaml override records."""
    cfg = _read_yaml(archive_path / ".openspec.yaml") or {}
    out = []
    for record in cfg.get("overrides") or []:
        key = str(record.get("key", ""))
        if key.startswith("signoff.") and record.get("after") == "approved":
            out.append((key.split(".", 1)[1], str(record.get("by", "?")), str(record.get("when", "?"))))
    return out


def log_path(root, cfg):
    return root / kb_of(cfg)["root"] / "log.md"


def capability_path(root, cfg, slug):
    return root / kb_of(cfg)["root"] / "capabilities" / f"{slug}.md"


def render_log_entry(name, date, caps, adrs, signoffs, cfg):
    lines = [f"### {name}", ""]
    if caps:
        links = ", ".join(f"[{c}](capabilities/{c}.md)" for c in caps)
        lines.append(f"- Capabilities: {links}")
    if adrs:
        lines.append(f"- ADRs: {', '.join(adrs)}")
    if signoffs:
        approved = ", ".join(f"{stage} ({by}, {when})" for stage, by, when in signoffs)
        lines.append(f"- Approved: {approved}")
    lines.append(f"- Archived: {date}")
    lines.append("")
    return "\n".join(lines)


def upsert_log(root, cfg, name, date, caps, adrs, signoffs):
    """Append the change's entry under its date heading. Idempotent: an entry
    for the same change name is never written twice."""
    path = log_path(root, cfg)
    text = path.read_text(encoding="utf-8") if path.is_file() else "# Log\n"
    if name in LOG_ENTRY_RE.findall(text):
        return False
    entry = render_log_entry(name, date, caps, adrs, signoffs, cfg)
    heading = f"## {date}"
    if heading in text:
        text = text.replace(heading, f"{heading}\n\n{entry}".rstrip() + "\n", 1)
    else:
        text = text.rstrip("\n") + f"\n\n{heading}\n\n{entry}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip("\n") + "\n", encoding="utf-8")
    return True


def render_stub(slug, date, adrs, author, spec_rel):
    front = [
        "---",
        "type: Capability",
        f"title: {_title(slug)}",
        f"created_ts: {date}T00:00:00Z",
        f"authors: [{author}]",
        "status: draft",
        f"generated: {{ by: {PRODUCER}, at: {_now()} }}",
        "sources:",
        f"  - resource: {spec_rel}",
        "    title: Canonical spec",
        "---",
        "",
        f"# {_title(slug)}",
        "",
        STUB_BODY,
    ]
    if adrs:
        front += ["## Governed by", ""] + [f"- {a}" for a in adrs] + [""]
    front += ["## Specification", "", f"Canonical behaviour: `{spec_rel}`", ""]
    return "\n".join(front)


def write_stubs(root, cfg, caps, date, adrs, author):
    created = []
    for slug in caps:
        path = capability_path(root, cfg, slug)
        if path.is_file():
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render_stub(slug, date, adrs, author, f"openspec/specs/{slug}/spec.md"), encoding="utf-8")
        created.append(slug)
    return created


def unfilled(root, cfg, caps):
    """Capability stubs whose body still carries the marker."""
    out = []
    for slug in caps:
        path = capability_path(root, cfg, slug)
        if path.is_file() and MARKER in path.read_text(encoding="utf-8", errors="replace"):
            out.append(slug)
    return out


def regenerate_index(root, cfg):
    """Rebuild <kb.root>/index.md: subsections first, then documents."""
    kb_root = root / kb_of(cfg)["root"]
    kb_root.mkdir(parents=True, exist_ok=True)
    dirs, docs = [], []
    for entry in sorted(kb_root.iterdir()):
        if entry.name.startswith("."):
            continue
        if entry.is_dir():
            dirs.append(entry.name)
        elif entry.suffix == ".md" and entry.name != "index.md":
            docs.append(entry.name)
    lines = ["# Knowledge base", ""]
    if dirs:
        lines += ["## Sections", ""] + [f"- [{d}]({d}/)" for d in dirs] + [""]
    if docs:
        lines += ["## Documents", ""] + [f"- [{Path(d).stem}]({d})" for d in docs] + [""]
    (kb_root / "index.md").write_text("\n".join(lines), encoding="utf-8")


def pending(root, cfg, name, caps):
    """Reasons the KB is not yet compounded for this change."""
    reasons = []
    path = log_path(root, cfg)
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    if name not in LOG_ENTRY_RE.findall(text):
        reasons.append(f"no log entry for {name!r} in {log_path(root, cfg).relative_to(root)}")
    for slug in caps:
        target = capability_path(root, cfg, slug)
        if not target.is_file():
            reasons.append(f"missing capability page: {target.relative_to(root)}")
    for slug in unfilled(root, cfg, caps):
        target = capability_path(root, cfg, slug)
        reasons.append(f"capability page still unwritten (remove the kb_compound marker): {target.relative_to(root)}")
    return reasons


def _main(args):
    root = args.repo.resolve()
    cfg, _ = load_workflow(root)
    if not kb_of(cfg)["enabled"]:
        if not args.check:
            print("kb.enabled is false — nothing to compound")
        return 0

    try:
        archive_path, name, date = resolve_archive(root, cfg, args.change)
    except GateError:
        # Nothing archived yet is not pending work — it is the answer to the
        # question. --check must not block S7 in a repo whose first change has
        # not reached archive. Write mode still reports the problem.
        if args.check and args.change is None:
            print("COMPOUND ok: nothing archived yet")
            return 0
        raise
    caps = capabilities_of(archive_path)
    adrs = adrs_of(archive_path)
    signoffs = signoffs_of(archive_path)
    author = next((f"human:{by}" for stage, by, _ in signoffs if stage == "archive"), PRODUCER)

    if args.check:
        reasons = pending(root, cfg, name, caps)
        if reasons:
            print(f"COMPOUND pending for {name}:")
            for reason in reasons:
                print(f"  - {reason}")
            return 1
        print(f"COMPOUND ok: {name} is folded into the knowledge base")
        return 0

    logged = upsert_log(root, cfg, name, date, caps, adrs, signoffs)
    created = write_stubs(root, cfg, caps, date, adrs, author)
    regenerate_index(root, cfg)

    print(f"COMPOUND {name}: log entry {'added' if logged else 'already present'}"
          f"; stubs created: {', '.join(created) if created else 'none'}")
    still = unfilled(root, cfg, caps)
    if still:
        print("  Write the why in:")
        for slug in still:
            print(f"    - {capability_path(root, cfg, slug).relative_to(root)}")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="Fold an archived change into the knowledge base")
    parser.add_argument("--change", metavar="NAME", help="archived change (default: most recent)")
    parser.add_argument("--check", action="store_true", help="report pending work and exit 1")
    parser.add_argument("--repo", metavar="ROOT", type=Path, default=REPO_ROOT, help="repo root")
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        return 1
    try:
        return _main(args)
    except GateError as exc:
        print(f"COMPOUND ERROR: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
