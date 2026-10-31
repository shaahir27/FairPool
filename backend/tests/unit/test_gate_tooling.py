import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_gate_rejects_unsupported_name_without_running_checks():
    result = subprocess.run(
        [sys.executable, str(ROOT / "tools/gate_check.py"), "ig-99"], capture_output=True, text=True
    )
    assert result.returncode == 2 and "invalid choice" in result.stderr


def test_ig2_rejects_pending_external_evidence():
    result = subprocess.run(
        [sys.executable, str(ROOT / "tools/gate_check.py"), "ig-2", "--evidence-only"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2 and "pending" in result.stdout


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
            {"run": run, "case_id": c["id"], "errors": []} for run in range(1, 4) for c in dataset
        ],
    }
    path = evidence / "gemini.json"
    monkeypatch.setenv("AI_MODEL_PARSE", "gemini-3.5-flash-lite")
    monkeypatch.setenv("AI_MODEL_SIM", "gemini-3.5-flash-lite")
    path.write_text(json.dumps(report))
    assert gate.evidence_errors(tmp_path) == []
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
