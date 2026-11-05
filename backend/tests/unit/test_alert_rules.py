"""T08A05: every alert names a real metric and every threshold is a real threshold."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from fairpool.infra.metrics import metric_names

ROOT = Path(__file__).resolve().parents[3]
ALERTS = ROOT / "deploy" / "alerts.yml"
METRIC_RE = re.compile(r"fairpool_[a-z_]+")
THRESHOLD_RE = re.compile(r"(?:>|<|>=|<=)\s*([0-9]+(?:\.[0-9]+)?)")
DURATION_RE = re.compile(r"^([0-9]+(?:\.[0-9]+)?)([smhd])$")


def rules() -> list[dict[str, Any]]:
    document = yaml.safe_load(ALERTS.read_text(encoding="utf-8"))
    loaded = [rule for group in document["groups"] for rule in group["rules"]]
    assert loaded
    return loaded


def test_every_alert_metric_is_emitted_by_the_metrics_module() -> None:
    emitted = metric_names()
    referenced: set[str] = set()
    for rule in rules():
        names = set(METRIC_RE.findall(str(rule["expr"])))
        assert names, rule["alert"]
        referenced |= names
        assert names <= emitted, f"{rule['alert']} names an unknown metric: {names - emitted}"
    assert {
        "fairpool_transitions_rejected_total",
        "fairpool_amount_mismatch_total",
        "fairpool_outcome_unknown_total",
        "fairpool_dead_letters",
    } <= referenced


def test_every_threshold_and_duration_is_non_zero() -> None:
    for rule in rules():
        thresholds = [float(value) for value in THRESHOLD_RE.findall(str(rule["expr"]))]
        assert thresholds, rule["alert"]
        assert all(value > 0 for value in thresholds), rule["alert"]
        if "for" in rule:
            match = DURATION_RE.fullmatch(str(rule["for"]))
            assert match is not None, rule["alert"]
            assert float(match.group(1)) > 0, rule["alert"]


def test_every_alert_is_actionable() -> None:
    for rule in rules():
        assert rule.get("alert"), rule
        assert rule.get("labels", {}).get("severity") in {"warning", "critical"}, rule
        assert rule.get("annotations", {}).get("summary"), rule


def test_a_stage_label_annotation_is_only_used_with_a_per_stage_aggregation() -> None:
    """``sum(...)`` drops the labels, so ``{{ $labels.stage }}`` would render empty."""
    for rule in rules():
        annotations = rule.get("annotations", {})
        text = " ".join(str(value) for value in annotations.values())
        if "$labels.stage" in text:
            assert "by (stage)" in str(rule["expr"]), rule["alert"]
