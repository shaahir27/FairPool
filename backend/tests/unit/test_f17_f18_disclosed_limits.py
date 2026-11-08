"""F17/F18: the two disclosed limits are stated, in the README and in the UI (I13).

Neither limit is detectable, so the only defence the product has is honest copy: a
reader must learn that duplicate control is account-level and does not prove one
person per account (F17), and that the published commitment list does not prove no
entry was omitted (F18). The tests read the shipped copy rather than a summary of it,
and also assert the stronger claims the product-spec forbids are absent.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
README = ROOT / "README.md"
BUYER_PAGES = ROOT / "frontend/src/buyer/pages.tsx"
POOL_PAGE = ROOT / "frontend/src/buyer/lobby/PoolPage.tsx"
AUDIT_PAGE = ROOT / "frontend/src/audit/AuditPage.tsx"


def flat(path: Path) -> str:
    """The file's text with runs of whitespace collapsed, so JSX line breaks do not hide it."""
    return re.sub(r"\s+", " ", path.read_text(encoding="utf-8"))


def test_f17_disclosed_limit_multiple_accounts() -> None:
    """F17 (I13): account-level duplicate control is stated, with its limit."""
    readme = flat(README)
    assert "Duplicate control is **account-level**" in readme
    assert (
        "one entry per linked PayPal account per pool where the PayPal Login account ID works, "
        "and account-level checks at checkout otherwise" in readme
    )
    assert "does not prove one human per account" in readme
    assert "does not eliminate bots or account farms" in readme

    buyer = flat(BUYER_PAGES)
    assert "does not prove one account per person" in buyer
    assert "One entry per linked PayPal account." in flat(POOL_PAGE)


def test_f18_disclosed_limit_omitted_entry() -> None:
    """F18 (I13): the audit copy says completeness is not proved."""
    readme = flat(README)
    assert "does **not** prove that no eligible entry was omitted" in readme
    assert 'it is not "provably fair"' in readme

    audit = flat(AUDIT_PAGE)
    assert "Completeness." in audit
    assert "the page cannot show that no entry was left out" in audit

    # The product-spec forbids presenting either limit as a guarantee: the stronger
    # wording appears only inside the README's "We do not claim" list, never as a claim.
    assert "bot-proof" not in readme
    assert "one person, one entry" not in audit
    do_not_claim = readme.index("**We do not claim:**")
    assert readme.count("one person, one entry") == 1
    assert readme.index("one person, one entry") > do_not_claim
