"""Fail-fast gate checks. Pending external evidence never closes IG-2."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from fairpool.db.safety import require_test_database

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_EVIDENCE = ("sandbox_contracts", "s4", "s8", "s13", "independent_review", "ci")


def evidence_errors(root: Path = ROOT) -> list[str]:
    evidence = root / "docs/evidence/phase2"
    errors = []
    for name in REQUIRED_EVIDENCE:
        path = evidence / f"{name}.json"
        if (
            not path.exists()
            or json.loads(path.read_text(encoding="utf-8")).get("status") != "passed"
        ):
            errors.append(f"{name}: required evidence pending")
    path = evidence / "gemini.json"
    if not path.exists():
        errors.append("Gemini: three live runs missing")
    else:
        report = json.loads(path.read_text(encoding="utf-8"))
        if report.get("status") != "passed" or len(report.get("results", [])) != 480:
            errors.append("Gemini: three complete accepted live runs pending")
        from evaluate_gemini import DATASET_REVISION
        from fairpool.adapters.ai.client import PROMPT_VERSION
        from fairpool.adapters.ai.schemas import SCHEMA_VERSION

        dataset = [
            json.loads(line)
            for path in sorted((root / "backend/tests/ai_eval/data").glob("*_cases.jsonl"))
            for line in path.read_text(encoding="utf-8").splitlines()
            if line
        ]
        expected = {
            "prompt_version": PROMPT_VERSION,
            "schema_version": SCHEMA_VERSION,
            "dataset_revision": DATASET_REVISION,
            "dataset_sha256": hashlib.sha256(
                json.dumps(dataset, sort_keys=True).encode()
            ).hexdigest(),
        }
        fingerprint = report.get("fingerprint", {})
        if any(fingerprint.get(k) != v for k, v in expected.items()):
            errors.append("Gemini: stale prompt/schema/dataset fingerprint")
        identities = {(r.get("run"), r.get("case_id")) for r in report.get("results", [])}
        if identities != {(run, c["id"]) for run in range(1, 4) for c in dataset}:
            errors.append("Gemini: incomplete or duplicate run/case identities")
        if any(r.get("errors") for r in report.get("results", [])):
            errors.append("Gemini: unresolved evaluation failures")
        for key, variable in (("model_parse", "AI_MODEL_PARSE"), ("model_sim", "AI_MODEL_SIM")):
            if fingerprint.get(key) != os.environ.get(variable, "gemini-3.5-flash-lite"):
                errors.append("Gemini: model changed since evaluation")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("gate", choices=("ig-0", "ig-1", "ig-2"))
    parser.add_argument("--evidence-only", action="store_true")
    args = parser.parse_args()
    if not args.evidence_only:
        if args.gate != "ig-0":
            require_test_database(os.environ.get("DATABASE_URL", ""))
            if os.environ.get("APP_ENV") != "test":
                raise ValueError("Automated gate migrations require APP_ENV=test")
        py = sys.executable
        npm = "npm.cmd" if os.name == "nt" else "npm"
        commands = [
            [py, "-m", "ruff", "check", "backend", "tools"],
            [py, "-m", "ruff", "format", "--check", "backend", "tools"],
            [
                py,
                "-m",
                "mypy",
                "--strict",
                "backend/src/fairpool/domain",
                "backend/src/fairpool/modules",
            ],
            [
                py,
                "-m",
                "pytest",
                "backend/tests",
                "-m",
                "not sandbox and not sandbox_interactive and not faults and not ai_eval",
            ],
            [py, "tools/check_imports.py"],
            [py, "tools/validate_docs.py"],
            [py, "tools/export_merchant_openapi.py", "--check"],
            [npm, "run", "lint", "--prefix", "frontend"],
            [npm, "test", "--prefix", "frontend"],
            [npm, "run", "build", "--prefix", "frontend"],
        ]
        if args.gate != "ig-0":
            commands.extend(
                [
                    [py, "-m", "alembic", "-c", "backend/alembic.ini", "upgrade", "head"],
                    [py, "-m", "alembic", "-c", "backend/alembic.ini", "check"],
                ]
            )
        if args.gate == "ig-2":
            commands.append([py, "tools/check_migrations.py"])
        commands.append([py, "tools/check_generated.py"])
        scanner = shutil.which("gitleaks")
        if scanner is None and os.name == "nt":
            scanner = next(
                (
                    str(p)
                    for p in Path(os.environ.get("LOCALAPPDATA", "")).glob(
                        "Microsoft/WinGet/Packages/Gitleaks.Gitleaks_*/gitleaks.exe"
                    )
                ),
                None,
            )
        if scanner is None:
            raise RuntimeError("gitleaks is required for gate verification")
        commands.append([scanner, "git", "--redact"])
        for command in commands:
            subprocess.run(command, cwd=ROOT, check=True)
    errors = evidence_errors() if args.gate == "ig-2" else []
    if errors:
        print("\n".join(errors))
        return 2
    print(f"{args.gate}: automated checks passed; recorded human checks still apply")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
