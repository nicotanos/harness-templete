"""Unit tests for scripts/kb_validate.py — OKF v0.2 conformance.

The spec's conformance section is narrow on purpose: only missing/unparseable
frontmatter and a missing `type` may fail a bundle. These tests lock that
boundary, because the temptation to promote a warning to an error is exactly
how a portable validator turns back into a house style.
"""

import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS_DIR))

import kb_validate as kv


def bundle(tmp_path, **files):
    root = tmp_path / "docs"
    root.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root


def run(root, *args):
    return kv.main([str(root), *args])


CONCEPT = "---\ntype: Reference\ntitle: Probe\n---\n\n# Probe\n"


# ------------------------------------------------------------- the two errors

def test_missing_frontmatter_fails(tmp_path, capsys):
    root = bundle(tmp_path, **{"a.md": "# No frontmatter\n"})
    assert run(root) == 1
    assert "missing YAML frontmatter" in capsys.readouterr().out


def test_missing_type_fails(tmp_path, capsys):
    root = bundle(tmp_path, **{"a.md": "---\ntitle: Probe\n---\n\n# Probe\n"})
    assert run(root) == 1
    assert "no non-empty 'type'" in capsys.readouterr().out


def test_unparseable_frontmatter_fails(tmp_path, capsys):
    root = bundle(tmp_path, **{"a.md": "---\ntype: [unclosed\n---\n\n# Probe\n"})
    assert run(root) == 1
    assert "unparseable YAML frontmatter" in capsys.readouterr().out


def test_minimal_conforming_document_passes(tmp_path):
    root = bundle(tmp_path, **{"a.md": "---\ntype: Metric\n---\n\n# Probe\n"})
    assert run(root, "--quiet") == 0


# -------------------------------------------- what the spec forbids rejecting

def test_unknown_type_is_accepted(tmp_path):
    """OKF: consumers MUST NOT reject a bundle for unknown types."""
    root = bundle(tmp_path, **{"a.md": "---\ntype: Playbook\ntitle: P\n---\n\nBody\n"})
    assert run(root, "--quiet") == 0


def test_unknown_keys_are_accepted(tmp_path):
    root = bundle(tmp_path, **{"a.md": "---\ntype: Reference\ntitle: P\nwhatever: 1\n---\n\nBody\n"})
    assert run(root, "--quiet") == 0


def test_broken_links_are_accepted(tmp_path):
    root = bundle(tmp_path, **{"a.md": CONCEPT + "\n[gone](./nowhere.md)\n"})
    assert run(root, "--quiet") == 0


def test_absent_index_is_accepted(tmp_path):
    """No index.md anywhere — still conforming."""
    root = bundle(tmp_path, **{"nested/a.md": CONCEPT})
    assert run(root, "--quiet") == 0


def test_reserved_files_need_no_type(tmp_path):
    root = bundle(tmp_path, **{
        "index.md": "# Index\n\n- [a](./a.md)\n",
        "log.md": "## 2026-08-28\n\n- created a\n",
        "a.md": CONCEPT,
    })
    assert run(root, "--quiet") == 0


# ----------------------------------------------------------------- advisories

def test_missing_title_warns_but_passes(tmp_path, capsys):
    root = bundle(tmp_path, **{"a.md": "---\ntype: Reference\n---\n\nBody\n"})
    assert run(root) == 0
    assert "missing 'title'" in capsys.readouterr().out


def test_bad_timestamp_warns_but_passes(tmp_path, capsys):
    root = bundle(tmp_path, **{"a.md": "---\ntype: Reference\ntitle: P\ncreated_ts: last tuesday\n---\n\nB\n"})
    assert run(root) == 0
    assert "is not an ISO 8601 datetime" in capsys.readouterr().out


def test_bad_actor_warns_but_passes(tmp_path, capsys):
    root = bundle(tmp_path, **{"a.md": "---\ntype: Reference\ntitle: P\nauthors: jane\n---\n\nB\n"})
    assert run(root) == 0
    assert "actor convention" in capsys.readouterr().out


def test_verified_entry_missing_at_warns(tmp_path, capsys):
    root = bundle(tmp_path, **{
        "a.md": "---\ntype: Reference\ntitle: P\nverified:\n  - by: human:jane\n---\n\nB\n"})
    assert run(root) == 0
    assert "missing 'at'" in capsys.readouterr().out


def test_stale_after_in_the_past_warns(tmp_path, capsys):
    root = bundle(tmp_path, **{
        "a.md": "---\ntype: Reference\ntitle: P\nstale_after: 2000-01-01T00:00:00Z\n---\n\nB\n"})
    assert run(root) == 0
    assert "content is stale" in capsys.readouterr().out


def test_sources_entry_without_resource_warns(tmp_path, capsys):
    root = bundle(tmp_path, **{
        "a.md": "---\ntype: Reference\ntitle: P\nsources:\n  - id: x\n---\n\nB\n"})
    assert run(root) == 0
    assert "needs a 'resource'" in capsys.readouterr().out


def test_strict_promotes_warnings_to_errors(tmp_path):
    root = bundle(tmp_path, **{"a.md": "---\ntype: Reference\n---\n\nBody\n"})
    assert run(root) == 0
    assert run(root, "--strict") == 1


# -------------------------------------------------------------------- plumbing

def test_hidden_directories_are_skipped(tmp_path):
    root = bundle(tmp_path, **{"a.md": CONCEPT, ".kb/notes.md": "# no frontmatter\n"})
    assert run(root, "--quiet") == 0


def test_relative_root_still_finds_documents(tmp_path, capsys, monkeypatch):
    """Regression: a `../docs` root once matched zero documents, because the
    hidden-path filter tested the '..' component."""
    bundle(tmp_path, **{"a.md": CONCEPT})
    monkeypatch.chdir(tmp_path / "docs")
    assert kv.main(["../docs"]) == 0
    assert "1 document(s)" in capsys.readouterr().out


def test_missing_directory_is_an_error(tmp_path):
    assert kv.main([str(tmp_path / "nope")]) == 1
