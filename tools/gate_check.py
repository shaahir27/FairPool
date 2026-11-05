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

# Each gate names the evidence it cannot close without. A file with a status other
# than "passed" keeps the gate red on purpose: a pending spike, an unreviewed
# phase or an owner decision nobody made is not automated acceptance.
GATE_EVIDENCE: dict[str, tuple[str, tuple[str, ...]]] = {
    "ig-2": (
        "phase2",
        ("sandbox_contracts", "s4", "s8", "s13", "independent_review", "ci"),
    ),
    "ig-3": (
        "phase3",
        (
            "migrations",
            "local_checks",
            "s5",
            "s10",
            "s11",
            "s12",
            "independent_review",
            "ci",
        ),
    ),
    "ig-4": (
        "phase4",
        ("migrations", "local_checks", "pipeline", "independent_review", "ci"),
    ),
    "ig-5": (
        "phase5",
        (
            "migrations",
            "local_checks",
            "it5_sandbox",
            "sandbox_contracts",
            "failure_net_zero",
            "auction_vectors",
            "merchant_bids",
            "independent_review",
            "ci",
        ),
    ),
    "ig-6": (
        "phase6",
        (
            "migrations",
            "local_checks",
            "auction_award",
            "webhook_delivery",
            "it6_sandbox",
            "sandbox_contracts",
            "failure_net_zero",
            "merchant_keys",
            "independent_review",
            "ci",
        ),
    ),
    "ig-7": (
        "phase7",
        (
            "migrations",
            "local_checks",
            "it7_sandbox",
            "sandbox_contracts",
            "independent_review",
            "ci",
        ),
    ),
    "ig-8": (
        "phase8",
        (
            "migrations",
            "local_checks",
            "it8_sandbox",
            "sim_10k",
            "s9",
            "sandbox_contracts",
            "independent_review",
            "ci",
        ),
    ),
}
REQUIRED_EVIDENCE = GATE_EVIDENCE["ig-2"][1]


def gemini_errors(evidence: Path, root: Path) -> list[str]:
    """The Phase 2 live-evaluation checks, kept exactly as they were."""
    errors: list[str] = []
    path = evidence / "gemini.json"
    if not path.exists():
        return ["Gemini: three live runs missing"]
    report = json.loads(path.read_text(encoding="utf-8"))
    if report.get("status") != "passed" or len(report.get("results", [])) != 480:
        errors.append("Gemini: three complete accepted live runs pending")
    from evaluate_gemini import (
        DATASET_REVISION,
        acceptance_errors,
        current_validator_errors,
        evidence_row_errors,
        v6_conflict_spot_errors,
        v7_conflict_spot_errors,
        v8_conflict_spot_errors,
    )
    from fairpool.adapters.ai.client import PROMPT_VERSION
    from fairpool.adapters.ai.schemas import SCHEMA_VERSION

    dataset = [
        json.loads(line)
        for path in sorted((root / "backend/tests/ai_eval/data").glob("*_cases.jsonl"))
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
    ]
    labelled_cases = {case["id"]: case for case in dataset}
    expected = {
        "prompt_version": PROMPT_VERSION,
        "schema_version": SCHEMA_VERSION,
        "dataset_revision": DATASET_REVISION,
        "dataset_sha256": hashlib.sha256(json.dumps(dataset, sort_keys=True).encode()).hexdigest(),
    }
    fingerprint = report.get("fingerprint", {})
    baseline_v4 = (
        PROMPT_VERSION == "phase2-gemini-v8"
        and fingerprint.get("prompt_version") == "phase2-gemini-v4"
    )
    baseline_expected = (
        {**expected, "prompt_version": "phase2-gemini-v4"} if baseline_v4 else expected
    )
    if any(fingerprint.get(k) != v for k, v in baseline_expected.items()):
        errors.append("Gemini: stale prompt/schema/dataset fingerprint")
    if baseline_v4:
        spot = report.get("v5_spot_checks", {})
        spot_fingerprint = spot.get("fingerprint", {})
        spot_results = spot.get("results", [])
        required_ids = {c["id"] for c in dataset if c["task"] in {"INTAKE", "QUOTE"}}
        required_ids.add("reconcile-009")
        spot_ids = [r.get("case_id") for r in spot_results]
        extraction = [r for r in spot_results if r.get("task") in {"INTAKE", "QUOTE"}]
        total = sum(r.get("expected_fields", 0) for r in extraction)
        matched = sum(r.get("matched_fields", 0) for r in extraction)
        if (
            any(
                spot_fingerprint.get(k) != v
                for k, v in {**expected, "prompt_version": "phase2-gemini-v5"}.items()
            )
            or any(
                spot_fingerprint.get(k) != fingerprint.get(k) for k in ("model_parse", "model_sim")
            )
            or not required_ids.issubset(set(spot_ids))
            or len(spot_ids) != len(set(spot_ids))
            or not total
            or matched / total < 0.95
            or acceptance_errors(spot_results)
            or evidence_row_errors(spot_results, labelled_cases, spot_fingerprint)
            or any(
                str(a.get("error", "")).startswith("PROVIDER_UNAVAILABLE")
                for r in spot_results
                for a in r.get("attempts", [])
            )
        ):
            errors.append("Gemini: missing or failed v5 spot checks")
        model = fingerprint.get("model_parse", "")
        if v6_conflict_spot_errors(report.get("v6_conflict_spots", {}), model):
            errors.append("Gemini: missing or failed v6 conflict spot checks")
        if v7_conflict_spot_errors(report.get("v7_conflict_spots", {}), model):
            errors.append("Gemini: missing or failed v7 conflict spot checks")
        if v8_conflict_spot_errors(report.get("v8_conflict_spots", {}), model):
            errors.append("Gemini: missing or failed v8 conflict spot checks")
        if current_validator_errors(report.get("results", []), labelled_cases, model) or (
            current_validator_errors(spot_results, labelled_cases, model)
        ):
            errors.append("Gemini: current validator rejected previous accepted outputs")
    identities = {(r.get("run"), r.get("case_id")) for r in report.get("results", [])}
    if identities != {(run, c["id"]) for run in range(1, 4) for c in dataset}:
        errors.append("Gemini: incomplete or duplicate run/case identities")
    results = report.get("results", [])
    if (
        evidence_row_errors(results, labelled_cases, fingerprint)
        or acceptance_errors(results)
        or any(
            str(a.get("error", "")).startswith("PROVIDER_UNAVAILABLE")
            for r in results
            for a in r.get("attempts", [])
        )
    ):
        errors.append("Gemini: unresolved evaluation failures")
    extraction = [r for r in results if r.get("task") in {"INTAKE", "QUOTE"}]
    expected_fields = sum(r.get("expected_fields", 0) for r in extraction)
    matched_fields = sum(r.get("matched_fields", 0) for r in extraction)
    if not expected_fields or matched_fields / expected_fields < 0.95:
        errors.append("Gemini: extraction accuracy below 95% or missing")
    for key, variable in (("model_parse", "AI_MODEL_PARSE"), ("model_sim", "AI_MODEL_SIM")):
        if fingerprint.get(key) != os.environ.get(variable, "gemini-3.5-flash-lite"):
            errors.append("Gemini: model changed since evaluation")
    return errors


def evidence_errors(root: Path = ROOT, gate: str = "ig-2") -> list[str]:
    directory, required = GATE_EVIDENCE[gate]
    evidence = root / "docs/evidence" / directory
    errors = []
    for name in required:
        path = evidence / f"{name}.json"
        if (
            not path.exists()
            or json.loads(path.read_text(encoding="utf-8")).get("status") != "passed"
        ):
            errors.append(f"{name}: required evidence pending")
    if gate == "ig-2":
        errors.extend(gemini_errors(evidence, root))
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("gate", choices=tuple(GATE_EVIDENCE) + ("ig-0", "ig-1"))
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
        if args.gate in ("ig-2", "ig-3", "ig-4", "ig-5", "ig-6", "ig-7", "ig-8"):
            commands.append([py, "tools/check_migrations.py"])
        if args.gate in ("ig-3", "ig-4", "ig-5", "ig-6", "ig-7", "ig-8"):
            # testing-strategy.md section 1: the fault suite is run by gate-check,
            # not by CI. IG-3 owns F5 and F16; IG-4 adds F7 and F8; IG-5 adds F9
            # and F24; IG-6 adds F2, F3, F4 and F10.
            commands.append([py, "-m", "pytest", "backend/tests/faults", "-m", "faults", "-q"])
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
    errors = evidence_errors(gate=args.gate) if args.gate in GATE_EVIDENCE else []
    if errors:
        print("\n".join(errors))
        return 2
    print(f"{args.gate}: automated checks passed; recorded human checks still apply")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
