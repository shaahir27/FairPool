from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
TOOL = REPO_ROOT / "tools" / "validate_docs.py"


def _run(docs: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(TOOL), "--docs", str(docs)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_real_docs_have_zero_errors() -> None:
    result = _run(REPO_ROOT / "docs")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "errors: 0" in result.stdout


def test_broken_fixture_fails_with_nonzero_exit(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "broken.md").write_text(
        "# Broken fixture\n\n| ID | Value |\n|---|---|\n| TBD | placeholder |\n",
        encoding="utf-8",
    )

    result = _run(docs)
    assert result.returncode != 0
    assert "forbidden text: TBD" in result.stdout
    assert "errors: 0" not in result.stdout


def test_agent_api_merges_before_same_phase_mcp(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    shutil.copytree(REPO_ROOT / "docs", docs)
    result = _run(docs)
    assert result.returncode == 0, result.stdout + result.stderr
    plan = docs / "implementation-plan.md"
    text = plan.read_text(encoding="utf-8").replace(
        "| T07A05 | A | L | T03B01, T04B01 |",
        "| T07A05 | A | L | T03B01, T04B01, T07B03 |",
    )
    assert text != plan.read_text(encoding="utf-8")
    plan.write_text(text, encoding="utf-8")
    result = _run(docs)
    assert result.returncode != 0
    assert "T07A05 (A) has a same-phase cross-owner dependency on T07B03" in result.stdout
