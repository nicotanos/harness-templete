#!/usr/bin/env python3
"""hook_gate.py — deterministic trigger for the SDD PreToolUse gates.

Claude Code's `if: "Bash(...)"` hook filter is BEST-EFFORT and FAILS OPEN
(documented in the hooks reference): when the Bash command contains $(),
backticks, or $VAR expansions (or cannot be parsed), a hook whose pattern
names more than a bare command runs regardless of whether the command
matches. A probe like

    python3 scripts/workflow_gate.py --change x 2>&1; echo "exit=$?"

therefore trips the S3/S6/S5 hooks on an unrelated command, and the gate's
exit 1 BLOCKS the probe. The `if` field cannot reliably enforce these
gates; enforcement must be deterministic, inside the hook handler.

This wrapper re-checks the actual Bash command (from the hook's stdin JSON)
against the commands each stage's gate is meant to guard, and only runs
scripts/workflow_gate.py when the command really is one of them. The stage
-> command mapping below is the single source of truth; the `if` matchers
in .claude/settings.json are only a spawn-saving fast path.

Usage (one hook handler per stage; keep `if` on the handler as a fast path):
    python3 scripts/hook_gate.py --stage S3

stdin: the PreToolUse JSON ({tool_name, tool_input:{command}}).

Exit codes:
    0  no output               — command does not match (or gate passed)
    1  GATE S# ... lines       — gate blocked, propagate to Claude Code
"""

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# Command prefixes each stage gate guards. `openspec` may be preceded by a
# VAR=value assignment and/or a python -m / npx runner (stripped before
# matching) and suffixed by `.cmd` on Windows.
STAGE_COMMANDS = {
    "S0": ("openspec new change", "openspec instructions proposal", "openspec instructions specs"),
    "S1": ("openspec instructions design",),
    "S2": ("openspec instructions tasks",),
    "S3": ("openspec instructions apply",),
    "S5": ("openspec validate --specs",),
    "S6": ("openspec archive",),
}

RUNNER_RE = re.compile(r"^(?:[A-Za-z_][A-Za-z0-9_]*=[^\s]+\s+)*(?:python3?\s+-m\s+|python\s+-m\s+|npx\s+)?")


def _prefix_regex(prefix):
    tokens = prefix.split()
    head = re.escape(tokens[0]) + r"(?:\.cmd)?"
    rest = r"\s+".join(re.escape(t) for t in tokens[1:])
    body = rf"\s+{rest}" if rest else ""
    return re.compile(rf"^{head}{body}(?:\s|$)")


PREFIX_RE = {stage: [_prefix_regex(p) for p in prefixes] for stage, prefixes in STAGE_COMMANDS.items()}


def subcommands(command):
    """Split a Bash command line into its subcommands (the shape Claude Code
    itself matches against), each with leading whitespace removed."""
    parts = re.split(r"[;&|]+", command)
    for part in parts:
        part = part.strip()
        if part:
            yield part


def command_matches(command, stage):
    """True when a subcommand of `command` runs one of the commands whose
    `stage` gate applies. Deterministic — never fails open."""
    regexes = PREFIX_RE.get(stage)
    if not regexes:
        return False
    for sub in subcommands(command):
        sub = RUNNER_RE.sub("", sub)
        if any(rx.match(sub) for rx in regexes):
            return True
    return False


def main(argv=None):
    parser = argparse.ArgumentParser(description="Deterministic gate trigger for SDD PreToolUse hooks")
    parser.add_argument("--stage", required=True, help="stage to gate, e.g. S3")
    parser.add_argument("--repo", type=Path, default=REPO_ROOT, help="repo root (default: parent of scripts/)")
    args = parser.parse_args(argv)

    raw = sys.stdin.read()
    command = ""
    if raw.strip():
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            data = {}
        if isinstance(data, dict):
            command = (data.get("tool_input") or {}).get("command", "") or ""

    if command and not command_matches(command, args.stage):
        return 0  # not a gated command — let it through, no output

    # Empty/unparseable stdin: cannot verify, so preserve the pre-wrapper
    # behavior (run the gate) rather than silently skipping enforcement.
    gate = args.repo.resolve() / "scripts" / "workflow_gate.py"
    if not gate.is_file():
        print(f"missing gate script: {gate}", file=sys.stderr)
        return 1
    python = shutil.which("python3") or shutil.which("python") or sys.executable
    proc = subprocess.run(
        [python, str(gate), "--stage", args.stage, "--repo", str(args.repo.resolve())],
        cwd=str(args.repo.resolve()), capture_output=True, text=True,
    )
    sys.stdout.write(proc.stdout)
    sys.stderr.write(proc.stderr)
    return proc.returncode


if __name__ == "__main__":
    sys.exit(main())
