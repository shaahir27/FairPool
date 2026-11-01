import importlib.util
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_ig2_acceptance_allows_safe_review_and_bounded_extraction_error(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "tools"))
    from evaluate_gemini import acceptance_errors, assessment

    case = {"task": "RECONCILE", "allow_review": False}
    assert assessment(case, None, True) == []
    assert assessment(case, None, True, provider_unavailable=True) == ["Provider unavailable"]
    results = [
        {"task": "INTAKE", "demo": False, "errors": ["Field mismatch: condition"]},
        {"task": "QUOTE", "demo": False, "errors": []},
    ]
    assert acceptance_errors(results) == []
    results[0]["errors"] = ["Field mismatch: max_total.amount"]
    assert acceptance_errors(results)
    results[0]["errors"] = ["Field mismatch: condition"]
    results[0]["demo"] = True
    assert acceptance_errors(results)


def test_live_evidence_rows_are_bound_to_labelled_cases(monkeypatch):
    import hashlib

    monkeypatch.syspath_prepend(str(ROOT / "tools"))
    from evaluate_gemini import evidence_row_errors

    from fairpool.domain.hashing import canonical_json

    case = {
        "id": "case-1",
        "task": "INTAKE",
        "demo": False,
        "allow_review": False,
        "expected": {"quantity": 1},
        "input": {"message": "example"},
    }
    row = {
        "case_id": "case-1",
        "task": "INTAKE",
        "demo": False,
        "review": False,
        "output": {"quantity": 1},
        "expected_fields": 1,
        "matched_fields": 1,
        "errors": [],
        "attempts": [
            {
                "ok": True,
                "output": {"quantity": 1},
                "error": None,
                "task": "INTAKE",
                "model": "m",
                "prompt_version": "v/phase2-v1",
                "input_hash": hashlib.sha256(
                    canonical_json({"message": "example"}).encode()
                ).hexdigest(),
            }
        ],
    }
    fingerprint = {
        "model_parse": "m",
        "model_sim": "m",
        "prompt_version": "v",
        "schema_version": "phase2-v1",
    }
    assert evidence_row_errors([row], {"case-1": case}, fingerprint) == []
    altered = {**row, "attempts": [{**row["attempts"][0], "input_hash": "wrong"}]}
    assert evidence_row_errors([altered], {"case-1": case}, fingerprint)
    assert evidence_row_errors([{**row, "attempts": []}], {"case-1": case})
    assert evidence_row_errors([{**row, "task": "QUOTE"}], {"case-1": case})
    assert evidence_row_errors([{**row, "matched_fields": 99}], {"case-1": case})
    assert evidence_row_errors([{**row, "output": None}], {"case-1": case})


def test_v6_conflict_spots_reject_missing_or_definite_capacity(monkeypatch):
    import hashlib

    monkeypatch.syspath_prepend(str(ROOT / "tools"))
    from evaluate_gemini import v6_conflict_spot_errors

    from fairpool.domain.hashing import canonical_json

    assert v6_conflict_spot_errors({}, "gemini-3.5-flash-lite")
    model = "gemini-3.5-flash-lite"
    texts = [
        "Capacity is 4 or 9; please confirm.",
        "Capacity is 4, but capacity is also 9 in a conflicting note.",
    ]
    rows = []
    for text in texts:
        digest = hashlib.sha256(
            canonical_json({"quote_text": text, "lot_requirement": {}}).encode()
        ).hexdigest()
        rows.append(
            {
                "quote_text": text,
                "output": None,
                "review": True,
                "attempts": [
                    {
                        "model": model,
                        "task": "QUOTE",
                        "prompt_version": "phase2-gemini-v6/phase2-v1",
                        "input_hash": digest,
                        "ok": False,
                        "error": "VALIDATION_FAILED: review",
                    }
                ],
            }
        )
    report = {
        "model": model,
        "prompt_version": "phase2-gemini-v6",
        "schema_version": "phase2-v1",
        "results": rows,
    }
    assert v6_conflict_spot_errors(report, model) == []
    rows[0]["attempts"][-1]["error"] = "PROVIDER_UNAVAILABLE"
    assert v6_conflict_spot_errors(report, model)


def test_gate_rejects_unsupported_name_without_running_checks():
    result = subprocess.run(
        [sys.executable, str(ROOT / "tools/gate_check.py"), "ig-99"], capture_output=True, text=True
    )
    assert result.returncode == 2 and "invalid choice" in result.stderr


def test_ig2_rejects_pending_external_evidence(tmp_path):
    """A single non-passed evidence file must keep IG-2 red.

    This used to assert the live repository had pending evidence, which made it a
    test of the repo's state rather than of the gate: once every item passed, the
    assertion became false for the wrong reason. It now builds a throwaway evidence
    set so the refusal is proved independently of what happens to be recorded.
    """
    importlib_ok = importlib.util.spec_from_file_location(
        "gate_under_test", ROOT / "tools" / "gate_check.py"
    )
    gate = importlib.util.module_from_spec(importlib_ok)
    assert importlib_ok.loader is not None
    importlib_ok.loader.exec_module(gate)
    evidence = tmp_path / "docs" / "evidence" / "phase2"
    evidence.mkdir(parents=True)
    directory, required = gate.GATE_EVIDENCE["ig-2"]
    assert directory == "phase2"
    for name in required:
        status = "pending" if name == "s13" else "passed"
        (evidence / f"{name}.json").write_text(json.dumps({"status": status}), encoding="utf-8")

    errors = gate.evidence_errors(root=tmp_path, gate="ig-2")
    assert any("s13" in error and "pending" in error for error in errors), errors
    assert not any("sandbox_contracts" in error for error in errors), errors


def test_gemini_evidence_rejects_stale_fingerprint_and_duplicate_cases(tmp_path, monkeypatch):
    import hashlib
    import importlib.util
    import json
    import shutil

    from fairpool.adapters.ai.client import PROMPT_VERSION
    from fairpool.adapters.ai.schemas import SCHEMA_VERSION

    monkeypatch.syspath_prepend(str(ROOT / "tools"))
    spec = importlib.util.spec_from_file_location("phase2_gate_test", ROOT / "tools/gate_check.py")
    gate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gate)
    import evaluate_gemini

    monkeypatch.setattr(evaluate_gemini, "evidence_row_errors", lambda *_: [])
    monkeypatch.setattr(evaluate_gemini, "current_validator_errors", lambda *_: [])
    monkeypatch.setattr(evaluate_gemini, "v6_conflict_spot_errors", lambda *_: [])
    monkeypatch.setattr(evaluate_gemini, "v7_conflict_spot_errors", lambda *_: [])
    monkeypatch.setattr(evaluate_gemini, "v8_conflict_spot_errors", lambda *_: [])
    from evaluate_gemini import DATASET_REVISION, cases

    dataset = cases()
    target = tmp_path / "backend/tests/ai_eval/data"
    shutil.copytree(ROOT / "backend/tests/ai_eval/data", target)
    evidence = tmp_path / "docs/evidence/phase2"
    evidence.mkdir(parents=True)
    for name in gate.REQUIRED_EVIDENCE:
        (evidence / f"{name}.json").write_text('{"status":"passed"}')
    fingerprint = {
        "model_parse": "gemini-3.5-flash-lite",
        "model_sim": "gemini-3.5-flash-lite",
        "prompt_version": PROMPT_VERSION,
        "schema_version": SCHEMA_VERSION,
        "dataset_revision": DATASET_REVISION,
        "dataset_sha256": hashlib.sha256(json.dumps(dataset, sort_keys=True).encode()).hexdigest(),
    }
    report = {
        "status": "passed",
        "fingerprint": fingerprint,
        "results": [
            {
                "run": run,
                "case_id": c["id"],
                "task": c["task"],
                "demo": c["demo"],
                "expected_fields": 1,
                "matched_fields": 1,
                "errors": [],
            }
            for run in range(1, 4)
            for c in dataset
        ],
    }
    path = evidence / "gemini.json"
    monkeypatch.setenv("AI_MODEL_PARSE", "gemini-3.5-flash-lite")
    monkeypatch.setenv("AI_MODEL_SIM", "gemini-3.5-flash-lite")
    path.write_text(json.dumps(report))
    assert gate.evidence_errors(tmp_path) == []
    result = next(r for r in report["results"] if r["task"] == "INTAKE" and not r["demo"])
    result["errors"] = ["Field mismatch: condition"]
    result["matched_fields"] = 0
    path.write_text(json.dumps(report))
    assert gate.evidence_errors(tmp_path) == []
    result["errors"] = ["Field mismatch: max_total.amount"]
    path.write_text(json.dumps(report))
    assert any("failures" in x for x in gate.evidence_errors(tmp_path))
    result["errors"] = []
    result["attempts"] = [{"error": "PROVIDER_UNAVAILABLE"}]
    path.write_text(json.dumps(report))
    assert any("failures" in x for x in gate.evidence_errors(tmp_path))
    result["attempts"] = []
    for row in report["results"]:
        if row["task"] in {"INTAKE", "QUOTE"}:
            row["matched_fields"] = 0
    path.write_text(json.dumps(report))
    assert any("accuracy" in x for x in gate.evidence_errors(tmp_path))
    for row in report["results"]:
        row["matched_fields"] = 1
    result["errors"] = []
    result["matched_fields"] = 1
    baseline_fingerprint = {**fingerprint, "prompt_version": "phase2-gemini-v4"}
    spot_cases = [c for c in dataset if c["task"] in {"INTAKE", "QUOTE"}]
    spot_cases += [c for c in dataset if c["id"] == "reconcile-009"]
    report["fingerprint"] = baseline_fingerprint
    report["v5_spot_checks"] = {
        "fingerprint": {**fingerprint, "prompt_version": "phase2-gemini-v5"},
        "results": [
            {
                "case_id": c["id"],
                "task": c["task"],
                "demo": c["demo"],
                "expected_fields": 1,
                "matched_fields": 1,
                "errors": [],
            }
            for c in spot_cases
        ],
    }
    path.write_text(json.dumps(report))
    assert gate.evidence_errors(tmp_path) == []
    report["v5_spot_checks"]["results"] = report["v5_spot_checks"]["results"][:-1]
    path.write_text(json.dumps(report))
    assert any("spot" in x for x in gate.evidence_errors(tmp_path))
    del report["v5_spot_checks"]
    report["fingerprint"] = fingerprint
    for field in ("prompt_version", "schema_version", "dataset_revision", "dataset_sha256"):
        original = fingerprint[field]
        fingerprint[field] = "changed"
        path.write_text(json.dumps(report))
        assert any("fingerprint" in x for x in gate.evidence_errors(tmp_path))
        fingerprint[field] = original
    report["results"][0] = report["results"][1]
    path.write_text(json.dumps(report))
    assert any("identities" in x for x in gate.evidence_errors(tmp_path))


async def test_live_evaluator_retains_failed_runs_and_prior_report(tmp_path, monkeypatch):
    import importlib.util
    import json

    monkeypatch.syspath_prepend(str(ROOT / "tools"))
    spec = importlib.util.spec_from_file_location(
        "phase2_eval_test", ROOT / "tools/evaluate_gemini.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    rows = [
        {
            "id": "fixture-good",
            "task": "INTAKE",
            "input": {},
            "expected": {"quantity": 1},
            "allow_review": False,
            "demo": True,
        },
        {
            "id": "fixture-failure",
            "task": "INTAKE",
            "input": {},
            "expected": {"quantity": 2},
            "allow_review": False,
            "demo": False,
        },
    ]
    monkeypatch.setattr(module, "cases", lambda: rows)
    monkeypatch.setenv("GEMINI_API_KEY", "unit-test-placeholder")

    class ScriptedFixture:
        def __init__(self, **kwargs):
            self.logger = kwargs["logger"]

        async def parse_intake(self, session, **kwargs):
            await self.logger.log(session, ok=True)
            return {"quantity": 1}

        parse_quote = parse_intake
        reconcile_offer = parse_intake
        sim_text = parse_intake

        async def close(self):
            pass

    monkeypatch.setattr(module, "GeminiAI", ScriptedFixture)
    path = tmp_path / "report.json"
    path.write_text('{"status":"failed","reason":"retained fixture failure"}')
    assert await module.evaluate(path, 1000) == 1
    report = json.loads(path.read_text())
    assert len(report["results"]) == 6
    assert sum(bool(r["errors"]) for r in report["results"]) == 3
    assert report["history"][0]["reason"] == "retained fixture failure"
    assert report["exact_extraction_field_accuracy"] == 0.5
