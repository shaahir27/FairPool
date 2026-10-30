from __future__ import annotations

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
