"""T09A03: the Render blueprint must not contradict what the README promises.

The hosted app is what a judge opens, so the deployment config and the demo
copy cannot drift. Two real drifts this file now pins: ``PAYMENT_MODE`` was set to
``vault_charge`` while the README promised per-buyer approval of the exact amount
(that mode rejects a live buyer with ``VAULT_MISSING``, DEP-5), and ``AI_ENABLED``
was false while the README described AI at the edges.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BLUEPRINT = ROOT / "deploy/render.yaml"
README = ROOT / "README.md"

_PAIR = re.compile(r"^\s*-\s+key:\s+(\w+)\n\s+value:\s*(.+)$", re.MULTILINE)


def blueprint_vars() -> dict[str, str]:
    """Every ``key``/``value`` pair declared in the blueprint.

    Parsed by line instead of with a YAML library: the file uses one flat shape
    (``- key:`` then ``value:``) and PyYAML is not a dependency of this project.
    shortcut: only flat key/value pairs are read; a nested value needs a real parser.
    """
    return {
        str(match[0]): str(match[1]).strip().strip('"')
        for match in _PAIR.findall(BLUEPRINT.read_text(encoding="utf-8"))
    }


def test_hosted_demo_mode_is_the_one_the_readme_promises() -> None:
    # T09A03 acceptance: the deployed mode matches the README headline.
    modes = blueprint_vars()["PAYMENT_MODE"]
    assert modes == "authorize_capture", (
        "the README promises each buyer approves their own PayPal payment for the exact"
        f" final amount, which only authorize_capture does; blueprint says {modes!r}"
    )
    assert "authorize_capture" in README.read_text(encoding="utf-8")


def test_blueprint_states_the_vault_save_limit() -> None:
    # DEP-5: real permission saving is unshipped, so the blueprint must say so
    # instead of letting the code default stand silently.
    assert blueprint_vars()["VAULT_REAL_SAVE_ENABLED"] == "false"


def test_free_web_service_starts_the_worker_with_the_api() -> None:
    blueprint = BLUEPRINT.read_text(encoding="utf-8")
    assert "dockerCommand: python -m fairpool.serve" in blueprint
    assert "plan: free" in blueprint
    dockerfile = (ROOT / "deploy/Dockerfile.api").read_text(encoding="utf-8")
    assert 'CMD ["python", "-m", "fairpool.serve"]' in dockerfile
    compose = (ROOT / "deploy/docker-compose.yml").read_text(encoding="utf-8")
    assert "command:" in compose and "exec uvicorn fairpool.main:app" in compose


def test_ai_cannot_be_switched_on_without_the_provider_key() -> None:
    # config.py refuses to start with AI_ENABLED=true and no GEMINI_API_KEY, which
    # would take down the whole public URL a judge opens.
    # shortcut: this can only check that the blueprint declares the secret slot; the
    # live Render group is outside the repo. Verify the group with the Render API
    # before flipping AI_ENABLED, which is how the Claude-names drift was found.
    declared = blueprint_vars()
    slot_declared = "GEMINI_API_KEY" in BLUEPRINT.read_text(encoding="utf-8")
    if declared["AI_ENABLED"] == "true":
        assert slot_declared, "AI_ENABLED=true needs the Gemini key declared in the ai group"


def test_ai_model_names_match_the_implemented_provider() -> None:
    # adapters/ai is google-genai only; a Claude model name here would fail at call
    # time rather than at start-up, which is the worse failure for a live demo.
    declared = blueprint_vars()
    if declared["AI_ENABLED"] == "true":
        for key in ("AI_MODEL_PARSE", "AI_MODEL_SIM"):
            assert declared[key].startswith("gemini"), (
                f"{key}={declared[key]!r} is not a Gemini model"
            )
