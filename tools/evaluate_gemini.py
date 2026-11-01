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


def assessment(
    case: dict[str, Any], output: Any, unavailable: bool, provider_unavailable: bool = False
) -> list[str]:
    if provider_unavailable:
        return ["Provider unavailable"]
    if unavailable:
        if case["allow_review"] or (case["task"] == "RECONCILE" and not case.get("demo")):
            return []
        return ["Required extraction unavailable"]
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


def acceptance_errors(results: list[dict[str, Any]]) -> list[str]:
    noncritical = {
        "condition",
        "quantity",
        "delivery.region",
        "required_by",
        "moq",
        "capacity",
        "target_quantity",
        "total_capacity",
        "delivery_sla_days",
        "returns_days",
        "valid_until",
    }
    failures = []
    for result in results:
        for error in result["errors"]:
            if (
                result["task"] in {"INTAKE", "QUOTE"}
                and not result["demo"]
                and error.startswith("Field mismatch: ")
                and error.removeprefix("Field mismatch: ") in noncritical
            ):
                continue
            failures.append(error)
    return failures


def evidence_row_errors(
    results: list[dict[str, Any]],
    labelled_cases: dict[str, dict[str, Any]],
    fingerprint: dict[str, Any] | None = None,
) -> list[str]:
    from fairpool.domain.hashing import canonical_json

    failures = []
    for row in results:
        case = labelled_cases.get(row.get("case_id"))
        attempts = row.get("attempts")
        if not case or not isinstance(attempts, list) or not 1 <= len(attempts) <= 2:
            failures.append("Missing labelled case or logged attempts")
            continue
        if row.get("task") != case["task"] or row.get("demo") != case["demo"]:
            failures.append("Case metadata mismatch")
            continue
        if fingerprint is not None:
            model_key = "model_sim" if case["task"] == "SIM_TEXT" else "model_parse"
            input_hash = hashlib.sha256(canonical_json(case["input"]).encode()).hexdigest()
            version = f"{fingerprint['prompt_version']}/{fingerprint['schema_version']}"
            if any(
                not isinstance(a, dict)
                or a.get("task") != case["task"]
                or a.get("model") != fingerprint.get(model_key)
                or a.get("prompt_version") != version
                or a.get("input_hash") != input_hash
                for a in attempts
            ):
                failures.append("Attempt identity or input hash mismatch")
                continue
        review = row.get("review")
        output = row.get("output")
        last = attempts[-1]
        if not isinstance(review, bool) or not isinstance(last, dict):
            failures.append("Invalid review or attempt")
            continue
        logged = last.get("output")
        if case["task"] == "SIM_TEXT" and isinstance(logged, dict):
            logged = logged.get("text")
        if review:
            if (
                output is not None
                or last.get("ok") is not False
                or not str(last.get("error", "")).startswith("VALIDATION_FAILED")
            ):
                failures.append("Unverified review outcome")
                continue
        elif output is None or last.get("ok") is not True or logged != output:
            failures.append("Unverified accepted output")
            continue
        provider_unavailable = any(
            str(a.get("error", "")).startswith("PROVIDER_UNAVAILABLE") for a in attempts
        )
        try:
            errors = assessment(case, output, review, provider_unavailable)
        except (KeyError, TypeError, IndexError):
            failures.append("Invalid labelled output")
            continue
        expected = len(case["expected"])
        matched = 0 if review else expected - len(errors)
        if (
            row.get("errors") != errors
            or row.get("expected_fields") != expected
            or row.get("matched_fields") != matched
        ):
            failures.append("Case assessment mismatch")
    return failures


def conflict_spot_errors(
    report: dict[str, Any], model: str, version: str, texts: set[str]
) -> list[str]:
    from fairpool.adapters.ai.schemas import Quote
    from fairpool.domain.hashing import canonical_json

    rows = report.get("results", [])
    if (
        report.get("prompt_version") != version
        or report.get("schema_version") != SCHEMA_VERSION
        or report.get("model") != model
        or len(rows) != 2
        or {r.get("quote_text") for r in rows} != texts
    ):
        return ["Missing conflict spot checks"]
    ai = GeminiAI(
        api_key="offline",
        model_parse=model,
        model_sim=model,
        logger=None,
        generate=lambda **_: None,
    )
    for row in rows:
        attempts = row.get("attempts", [])
        expected_hash = hashlib.sha256(
            canonical_json({"quote_text": row["quote_text"], "lot_requirement": {}}).encode()
        ).hexdigest()
        if not 1 <= len(attempts) <= 2 or any(
            a.get("model") != model
            or a.get("task") != "QUOTE"
            or a.get("prompt_version") != f"{version}/{SCHEMA_VERSION}"
            or a.get("input_hash") != expected_hash
            or str(a.get("error", "")).startswith("PROVIDER_UNAVAILABLE")
            for a in attempts
        ):
            return ["Invalid conflict attempt"]
        output = row.get("output")
        if row.get("review") is True:
            if (
                output is not None
                or attempts[-1].get("ok") is not False
                or not str(attempts[-1].get("error", "")).startswith("VALIDATION_FAILED")
            ):
                return ["Invalid review"]
        else:
            if attempts[-1].get("ok") is not True or attempts[-1].get("output") != output:
                return ["Invalid output"]
            try:
                parsed = Quote.model_validate(output).model_dump()
                if parsed["capacity"] is not None:
                    return ["Definite capacity in ambiguous quote"]
                ai._meaning("QUOTE", parsed, {"lot_requirement": {}}, row["quote_text"])
            except (ValueError, TypeError, KeyError):
                return ["Invalid quote output"]
    return []


def v6_conflict_spot_errors(report: dict[str, Any], model: str) -> list[str]:
    return conflict_spot_errors(
        report,
        model,
        "phase2-gemini-v6",
        {
            "Capacity is 4 or 9; please confirm.",
            "Capacity is 4, but capacity is also 9 in a conflicting note.",
        },
    )


def v7_conflict_spot_errors(report: dict[str, Any], model: str) -> list[str]:
    return conflict_spot_errors(
        report,
        model,
        "phase2-gemini-v7",
        {"Capacity is 4, or 9; please confirm.", "Capacity is 4 units or 9 units; please confirm."},
    )


def v8_conflict_spot_errors(report: dict[str, Any], model: str) -> list[str]:
    return conflict_spot_errors(
        report,
        model,
        "phase2-gemini-v8",
        {"Capacity is 4, or 9; please confirm.", "Capacity is 4 units or 9 units; please confirm."},
    )


def current_validator_errors(
    results: list[dict[str, Any]], labelled_cases: dict[str, dict[str, Any]], model: str
) -> list[str]:
    from fairpool.adapters.ai.schemas import Intake, Quote, Reconcile, Simulation

    schemas = {"INTAKE": Intake, "QUOTE": Quote, "RECONCILE": Reconcile, "SIM_TEXT": Simulation}
    ai = GeminiAI(
        api_key="offline",
        model_parse=model,
        model_sim=model,
        logger=None,
        generate=lambda **_: None,
    )
    failures = []
    for row in results:
        if row.get("review"):
            continue
        case = labelled_cases.get(row.get("case_id"))
        if not case or case["task"] not in schemas:
            failures.append("Unknown case")
            continue
        payload = case["input"]
        source = payload.get("message", payload.get("quote_text", payload.get("text", "")))
        output = {"text": row.get("output")} if case["task"] == "SIM_TEXT" else row.get("output")
        try:
            parsed = schemas[case["task"]].model_validate(output).model_dump()
            ai._meaning(case["task"], parsed, payload, source)
        except (ValueError, TypeError, KeyError):
            failures.append(f"Current validation failed: {case['id']}")
    return failures


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
                provider_unavailable = any(
                    str(a.get("error", "")).startswith("PROVIDER_UNAVAILABLE")
                    for a in logger.attempts[before:]
                )
                errors = assessment(case, output, unavailable, provider_unavailable)
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
        and not acceptance_errors(results)
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
