"""Run all 160 synthetic cases three times through the production Gemini adapter.

Requires an explicitly exported key and account quota. Never loads .env or uses
fake responses. A failed or incomplete report is not demo acceptance evidence.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fairpool.adapters.ai.client import PROMPT_VERSION, AIUnavailable, GeminiAI
from fairpool.adapters.ai.schemas import SCHEMA_VERSION

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "backend/tests/ai_eval/data"
DATASET_REVISION = "phase2-synthetic-v2"


class AttemptLogger:
    def __init__(self) -> None:
        self.attempts: list[dict[str, Any]] = []

    async def log(self, session: Any, **values: Any) -> None:
        self.attempts.append(values)


def cases() -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for path in sorted(DATA.glob("*_cases.jsonl"))
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
    ]


def assessment(case: dict[str, Any], output: Any, unavailable: bool) -> list[str]:
    if unavailable:
        return [] if case["allow_review"] else ["Required extraction unavailable"]
    errors = []
    for key, expected in case["expected"].items():
        if key == "review":
            errors.append("Ambiguous case was accepted instead of requiring review")
        elif key == "flag_code":
            if expected not in {f["code"] for f in output["flags"]}:
                errors.append("Expected contradiction code missing")
        elif key == "clarification":
            if not output.get("clarifying_question") and not output.get("ambiguities"):
                errors.append("Missing clarification")
        elif key == "facts":
            # The production adapter validates every supplied fact before returning text.
            if not isinstance(output, str):
                errors.append("Simulation text missing")
        else:
            value = output
            try:
                for part in key.split("."):
                    value = value[int(part)] if isinstance(value, list) else value[part]
            except (KeyError, IndexError, TypeError, ValueError):
                value = object()
            if value != expected:
                errors.append(f"Field mismatch: {key}")
    return errors


async def evaluate(
    report_path: Path,
    rpm: int,
    case_ids: list[str] | None = None,
    runs: int = 3,
) -> int:
    all_cases = cases()
    if case_ids:
        wanted = set(case_ids)
        known = {c["id"] for c in all_cases}
        unknown = wanted - known
        if unknown:
            raise SystemExit(f"Unknown case ids: {', '.join(sorted(unknown))}")
        dataset = [c for c in all_cases if c["id"] in wanted]
    else:
        dataset = all_cases
    model_parse = os.environ.get("AI_MODEL_PARSE", "gemini-3.5-flash-lite")
    model_sim = os.environ.get("AI_MODEL_SIM", "gemini-3.5-flash-lite")
    fingerprint = dict(
        model_parse=model_parse,
        model_sim=model_sim,
        prompt_version=PROMPT_VERSION,
        schema_version=SCHEMA_VERSION,
        dataset_revision=DATASET_REVISION,
        dataset_sha256=hashlib.sha256(json.dumps(dataset, sort_keys=True).encode()).hexdigest(),
    )
    report: dict[str, Any] = dict(
        fingerprint=fingerprint,
        started_at=datetime.now(UTC).isoformat(),
        status="pending",
        reason=None,
        selection={"case_ids": case_ids, "runs": runs},
        results=[],
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    if report_path.exists():
        previous = json.loads(report_path.read_text(encoding="utf-8"))
        history = previous.pop("history", [])
        report["history"] = [*history, previous]

    def save() -> None:
        report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    if not os.environ.get("GEMINI_API_KEY"):
        report["reason"] = "GEMINI_API_KEY not exported; no live calls made"
        save()
        print(report["reason"])
        return 2
    logger = AttemptLogger()
    ai = GeminiAI(
        api_key=os.environ["GEMINI_API_KEY"],
        model_parse=model_parse,
        model_sim=model_sim,
        logger=logger,
    )
    methods = {
        "INTAKE": ai.parse_intake,
        "QUOTE": ai.parse_quote,
        "RECONCILE": ai.reconcile_offer,
        "SIM_TEXT": ai.sim_text,
    }
    # Enforce quota between individual SDK attempts, including validation retries.
    last_started = 0.0

    async def limited() -> None:
        nonlocal last_started
        loop = asyncio.get_running_loop()
        delay = 60 / rpm - (loop.time() - last_started)
        if delay > 0:
            await asyncio.sleep(delay)
        last_started = loop.time()

    ai.before_attempt = limited
    try:
        for run in range(1, runs + 1):
            for case in dataset:
                before = len(logger.attempts)
                output, unavailable = None, False
                try:
                    output = await methods[case["task"]](None, **case["input"])
                except AIUnavailable:
                    unavailable = True
                errors = assessment(case, output, unavailable)
                report["results"].append(
                    dict(
                        run=run,
                        case_id=case["id"],
                        task=case["task"],
                        demo=case["demo"],
                        expected_fields=len(case["expected"]),
                        matched_fields=0 if unavailable else len(case["expected"]) - len(errors),
                        output=output,
                        review=unavailable,
                        errors=errors,
                        attempts=logger.attempts[before:],
                    )
                )
                save()
    finally:
        await ai.close()
    results = report["results"]
    extraction = [r for r in results if r["task"] in {"INTAKE", "QUOTE"}]
    if extraction:
        accuracy = sum(r["matched_fields"] for r in extraction) / sum(
            r["expected_fields"] for r in extraction
        )
        case_accuracy = sum(not r["errors"] for r in extraction) / len(extraction)
    else:
        accuracy = case_accuracy = 0.0
    report["exact_extraction_field_accuracy"] = accuracy
    report["exact_extraction_case_accuracy"] = case_accuracy
    report["completed_at"] = datetime.now(UTC).isoformat()
    report["status"] = (
        "passed"
        if len(results) == len(dataset) * runs
        and accuracy >= 0.95
        and not any(r["errors"] for r in results)
        else "failed"
    )
    save()
    print(f"Live evaluation {report['status']}: {len(results)} recorded cases")
    return 0 if report["status"] == "passed" else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--requests-per-minute",
        type=int,
        required=True,
        help="The account's verified quota; includes validation retries",
    )
    parser.add_argument("--report", type=Path, default=ROOT / "docs/evidence/phase2/gemini.json")
    parser.add_argument(
        "--case-ids",
        help="Comma-separated case IDs for a diagnostic subset",
    )
    parser.add_argument("--runs", type=int, default=3)
    args = parser.parse_args()
    if args.requests_per_minute < 1:
        parser.error("quota must be positive")
    if args.runs < 1:
        parser.error("runs must be positive")
    ids = (
        [item.strip() for item in args.case_ids.split(",") if item.strip()]
        if args.case_ids
        else None
    )
    return asyncio.run(evaluate(args.report, args.requests_per_minute, ids, args.runs))


if __name__ == "__main__":
    raise SystemExit(main())
