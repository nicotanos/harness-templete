#!/usr/bin/env python3
"""harness_doctor.py — what is set up, and what is still yours to do.

Usage: python3 scripts/harness_doctor.py [--repo ROOT]

Answers two questions a fresh copy of this template cannot answer from its
README: is the harness actually working here, and which decisions has nobody
made yet. Both are computed, so neither goes stale the way a checklist does.

Checks fall into three kinds:

    ok      done, nothing to do
    todo    the harness is not usable until this is fixed
    yours   a deliberate blank the template leaves for the project to fill

Exit code: 0 when no `todo` remains. `yours` items never affect the exit code —
they are decisions, not failures, and a project may reasonably leave some of
them open for a long time.
"""

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

OK, TODO, YOURS = "ok", "todo", "yours"
MARK = {OK: "  ok  ", TODO: " TODO ", YOURS: "yours "}

# Phrases that only appear in the template's own README, never in a project's.
TEMPLATE_README_TELLS = ("A template repo for artifact-enforced", "# SDD Harness")


class Report:
    def __init__(self):
        self.rows = []

    def add(self, kind, title, detail=""):
        self.rows.append((kind, title, detail))

    def render(self):
        width = max((len(t) for _, t, _ in self.rows), default=0)
        for kind, title, detail in self.rows:
            print(f"[{MARK[kind]}] {title.ljust(width)}  {detail}".rstrip())
        todo = sum(1 for k, _, _ in self.rows if k == TODO)
        yours = sum(1 for k, _, _ in self.rows if k == YOURS)
        print()
        if todo:
            print(f"{todo} thing(s) to fix before the harness works here.")
        else:
            print("The harness is working.")
        if yours:
            print(f"{yours} decision(s) still open — yours to make, not blockers.")
        return 1 if todo else 0


def _run(argv, cwd):
    try:
        p = subprocess.run(argv, cwd=str(cwd), capture_output=True, text=True, timeout=60)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except (OSError, subprocess.SubprocessError):
        return 127, ""


def check_python_deps(report):
    try:
        import yaml  # noqa: F401
        report.add(OK, "PyYAML", "the gate can run")
    except ImportError:
        report.add(TODO, "PyYAML", "python3 -m pip install -r requirements.txt")


def check_openspec(report, root):
    binary = shutil.which("openspec") or shutil.which("openspec.cmd")
    if not binary:
        report.add(TODO, "openspec CLI", "npm install -g @fission-ai/openspec")
        return
    rc, out = _run([binary, "--version"], root)
    version = out.strip().splitlines()[0] if rc == 0 and out.strip() else "unknown"
    report.add(OK, "openspec CLI", f"v{version.lstrip('v')}")


def check_opsx_commands(report, root):
    """`openspec update` generates these; the template does not vendor them."""
    commands = root / ".claude" / "commands" / "opsx"
    count = len(list(commands.glob("*.md"))) if commands.is_dir() else 0
    if count:
        report.add(OK, "/opsx: commands", f"{count} generated")
    else:
        report.add(TODO, "/opsx: commands", "openspec update  (the template does not vendor them)")


def check_gate(report, root):
    gate = root / "scripts" / "workflow_gate.py"
    if not gate.is_file():
        report.add(TODO, "gate script", "scripts/workflow_gate.py is missing")
        return
    rc, out = _run([sys.executable, str(gate), "--repo", str(root)], root)
    first = (out.strip().splitlines() or [""])[0]
    if first.startswith("GATE ERROR"):
        report.add(TODO, "gate", first)
    else:
        report.add(OK, "gate", first)


def check_git_hook(report, root):
    hook = root / ".git" / "hooks" / "pre-commit"
    if hook.is_file():
        report.add(OK, "git pre-commit hook", "installed (warn-only)")
    else:
        report.add(YOURS, "git pre-commit hook", "cp scripts/pre-commit .git/hooks/ && chmod +x .git/hooks/pre-commit")


def check_adrs(report, root, cfg):
    from workflow_gate import adr_dir  # local import: needs PyYAML
    folder = root / adr_dir(cfg)
    adrs = sorted(folder.glob("*.md")) if folder.is_dir() else []
    own = [p for p in adrs if not p.name.startswith("ADR-0001-artifact-enforced")]
    if not adrs:
        report.add(TODO, "ADRs", f"Stage 2 needs at least one file in {adr_dir(cfg)}/")
    elif not own:
        report.add(YOURS, "ADRs", f"only the seed ADR — record your own decisions in {adr_dir(cfg)}/ (see templates/adr.md)")
    else:
        report.add(OK, "ADRs", f"{len(adrs)} in {adr_dir(cfg)}/")


def check_readme(report, root):
    readme = root / "README.md"
    if not readme.is_file():
        report.add(YOURS, "README", "write one describing this project")
        return
    text = readme.read_text(encoding="utf-8", errors="replace")
    if any(tell in text for tell in TEMPLATE_README_TELLS):
        report.add(YOURS, "README", "still describes the harness — replace it with this project's")
    else:
        report.add(OK, "README", "project's own")


def check_kb(report, root, cfg):
    from workflow_gate import kb_of, run_kb_validate
    kb = kb_of(cfg)
    if not kb["enabled"]:
        report.add(YOURS, "knowledge base", "off (default) — set kb.enabled in .openspec/workflow.yaml to turn it on")
        return
    try:
        ok, out = run_kb_validate(root, cfg)
    except Exception as exc:  # GateError and friends
        report.add(TODO, "knowledge base", str(exc))
        return
    if ok:
        report.add(OK, "knowledge base", f"enabled, {kb['root']}/ validates")
    else:
        first = (out.strip().splitlines() or [""])[0]
        report.add(TODO, "knowledge base", f"enabled but invalid: {first}")


def check_pipeline_ignored(report, root, cfg):
    from workflow_gate import paths_of
    pipeline = paths_of(cfg)["pipeline_dir"]
    gitignore = root / ".gitignore"
    text = gitignore.read_text(encoding="utf-8", errors="replace") if gitignore.is_file() else ""
    if re.search(rf"^{re.escape(pipeline.rstrip('/'))}/?\s*$", text, re.MULTILINE):
        report.add(OK, "transient reports ignored", f"{pipeline}/ in .gitignore")
    else:
        report.add(TODO, "transient reports ignored", f"add {pipeline}/ to .gitignore — stage reports must not be committed")


def check_plugins(report, root):
    settings = root / ".claude" / "settings.json"
    if not settings.is_file():
        report.add(TODO, "Claude Code hooks", ".claude/settings.json is missing — the gate is not enforced")
        return
    try:
        data = json.loads(settings.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        report.add(TODO, "Claude Code hooks", f".claude/settings.json is invalid JSON: {exc}")
        return
    hooks = data.get("hooks") or {}
    total = sum(len(v) for v in hooks.values() if isinstance(v, list))
    report.add(OK if total else TODO, "Claude Code hooks", f"{total} configured" if total else "no hooks — the gate is not enforced")
    if data.get("enabledPlugins"):
        report.add(OK, "plugin requests", ", ".join(data["enabledPlugins"]))


def check_license(report, root):
    if (root / "LICENSE").is_file():
        report.add(OK, "LICENSE", "present")
    else:
        report.add(YOURS, "LICENSE", "none — the template's MIT does not carry over automatically")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Report harness setup state and open decisions")
    parser.add_argument("--repo", metavar="ROOT", type=Path, default=REPO_ROOT)
    args = parser.parse_args(argv)
    root = args.repo.resolve()

    print(f"SDD harness — {root}\n")
    report = Report()

    check_python_deps(report)
    try:
        import yaml  # noqa: F401
    except ImportError:
        # Everything below needs the config layer; stop with what we know.
        report.add(TODO, "further checks", "install dependencies first, then re-run")
        return report.render()

    sys.path.insert(0, str(root / "scripts"))
    try:
        from workflow_gate import load_workflow
        cfg, _ = load_workflow(root)
    except Exception as exc:
        report.add(TODO, "workflow config", str(exc))
        return report.render()

    check_openspec(report, root)
    check_opsx_commands(report, root)
    check_plugins(report, root)
    check_gate(report, root)
    check_pipeline_ignored(report, root, cfg)
    check_kb(report, root, cfg)
    check_adrs(report, root, cfg)
    check_git_hook(report, root)
    check_readme(report, root)
    check_license(report, root)
    return report.render()


if __name__ == "__main__":
    sys.exit(main())
