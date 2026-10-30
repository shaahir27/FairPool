from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
TOOL = REPO_ROOT / "tools" / "check_imports.py"


def _load_checker() -> ModuleType:
    spec = importlib.util.spec_from_file_location("fairpool_check_imports", TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


check_imports = _load_checker()


def _write(root: Path, relative: str, text: str) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _scan(root: Path) -> list[object]:
    return check_imports.scan(root)


def _rules(root: Path) -> set[int]:
    return {violation.rule for violation in _scan(root)}


def test_current_tree_is_clean() -> None:
    assert _scan(REPO_ROOT) == []


def test_missing_directories_are_skipped(tmp_path: Path) -> None:
    assert _scan(tmp_path) == []


def test_domain_allows_stdlib_pydantic_own_code_and_hashing_cryptography(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "backend/src/fairpool/domain/money.py",
        "from __future__ import annotations\n"
        "from dataclasses import dataclass\n"
        "from pydantic import BaseModel\n"
        "from fairpool.domain import errors\n",
    )
    _write(
        tmp_path,
        "backend/src/fairpool/domain/hashing.py",
        "from cryptography.hazmat.primitives import hashes\n",
    )
    assert _scan(tmp_path) == []


def test_domain_rejects_foreign_imports(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "backend/src/fairpool/domain/money.py",
        "import sqlalchemy\n"
        "from fairpool.ports import PaymentRouter\n"
        "from cryptography.hazmat.primitives import hashes\n",
    )
    assert _rules(tmp_path) == {1}


def test_ai_adapter_allows_its_declared_imports(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "backend/src/fairpool/adapters/ai/client.py",
        "from anthropic import Anthropic\n"
        "import httpx\n"
        "from pydantic import BaseModel\n"
        "from fairpool.ports import AIProposal\n"
        "from fairpool.domain import errors\n",
    )
    assert _scan(tmp_path) == []


def test_ai_adapter_rejects_checkout_and_other_sdks(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "backend/src/fairpool/adapters/ai/client.py",
        "from fairpool.modules import checkout\n"
        "from fairpool.adapters.paypal import gateway\n"
        "import openai\n",
    )
    assert 2 in _rules(tmp_path)


def test_paypal_importers_are_restricted_and_adapter_has_no_modules(tmp_path: Path) -> None:
    allowed = [
        "backend/src/fairpool/modules/checkout/engine.py",
        "backend/src/fairpool/modules/webhooks/handler.py",
        "backend/src/fairpool/modules/reconciler/loop.py",
        "backend/src/fairpool/modules/fulfillment/service.py",
        "backend/src/fairpool/wiring.py",
        "backend/src/fairpool/api/routers/checkout.py",
        "backend/src/fairpool/api/routers/webhooks.py",
        "backend/src/fairpool/api/routers/admin_ops.py",
        "backend/src/fairpool/api/routers/health.py",
        "backend/src/fairpool/api/routers/merchant_fulfillment.py",
    ]
    for relative in allowed:
        _write(tmp_path, relative, "from fairpool.adapters.paypal import gateway\n")
    _write(
        tmp_path,
        "backend/tests/unit/test_gateway.py",
        "from fairpool.adapters.paypal import gateway\n",
    )
    _write(
        tmp_path,
        "backend/src/fairpool/modules/pools/service.py",
        "from fairpool.adapters.paypal import gateway\n",
    )
    _write(
        tmp_path,
        "backend/src/fairpool/api/routers/pools.py",
        "from fairpool.adapters.paypal import gateway\n",
    )
    _write(
        tmp_path,
        "backend/src/fairpool/adapters/paypal/gateway.py",
        "from fairpool.modules import checkout\n",
    )

    violations = _scan(tmp_path)
    assert {violation.rule for violation in violations} == {3}
    assert {violation.path.name for violation in violations} == {
        "service.py",
        "pools.py",
        "gateway.py",
    }


def test_sim_never_imports_paypal(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "backend/src/fairpool/modules/sim/engine.py",
        "from fairpool.adapters.paypal import gateway\n",
    )
    assert _rules(tmp_path) == {4}

    _write(
        tmp_path,
        "backend/src/fairpool/modules/sim/search.py",
        "from fairpool.adapters.search import SearchService\n"
        "from fairpool.ports import PaymentRouter\n",
    )
    assert _rules(tmp_path) == {4}


def test_module_groups_do_not_import_each_other(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "backend/src/fairpool/modules/identity/service.py",
        "from fairpool.modules import ledger\nfrom fairpool.infra import jobs\n",
    )
    _write(
        tmp_path,
        "backend/src/fairpool/modules/ledger/service.py",
        "from fairpool.modules.identity import identity\n",
    )
    _write(
        tmp_path,
        "backend/src/fairpool/wiring.py",
        "from fairpool.modules import checkout, identity\n",
    )
    assert _rules(tmp_path) == {5}

    clean_root = tmp_path / "clean"
    _write(
        clean_root,
        "backend/src/fairpool/modules/checkout/engine.py",
        "from fairpool.modules import ledger\nfrom fairpool.infra import jobs\n",
    )
    _write(
        clean_root,
        "backend/src/fairpool/modules/identity/service.py",
        "from fairpool.modules import pools\n",
    )
    assert _scan(clean_root) == []


def test_search_adapter_has_no_money_or_ai_run_imports(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "backend/src/fairpool/adapters/search/elastic.py",
        "from fairpool.modules import ledger\n"
        "from fairpool.modules import checkout\n"
        "from fairpool.adapters import ai\n"
        "from fairpool.adapters.paypal import gateway\n",
    )
    assert 6 in _rules(tmp_path)

    clean_root = tmp_path / "clean"
    _write(
        clean_root,
        "backend/src/fairpool/adapters/search/postgres.py",
        "import httpx\n"
        "from fairpool.ports import SearchService\n"
        "from fairpool.domain import errors\n"
        "from fairpool.modules.pools import Pool\n",
    )
    assert _scan(clean_root) == []


def test_mcp_and_agentapi_import_no_member_a_modules(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "backend/src/fairpool/modules/mcp/server.py",
        "from fairpool.modules import checkout\n",
    )
    _write(
        tmp_path,
        "backend/src/fairpool/modules/agentapi/routes.py",
        "from fairpool.modules import webhooks\n",
    )
    assert _rules(tmp_path) == {7}


def test_mcp_and_agentapi_expose_no_payment_tools(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "backend/src/fairpool/modules/mcp/server.py",
        "async def list_pools():\n    ...\n\n"
        "async def capture_payment():\n    ...\n\n"
        "async def create_order_tool():\n    ...\n",
    )
    _write(
        tmp_path,
        "backend/src/fairpool/modules/agentapi/routes.py",
        "from fastapi import APIRouter\n\n"
        "router = APIRouter()\n\n"
        '@router.post("/offers/{buyer_order_id}/authorize")\n'
        "def approve():\n    ...\n",
    )
    violations = _scan(tmp_path)
    assert {violation.rule for violation in violations} == {7}
    assert any("capture_payment" in violation.message for violation in violations)
    assert any("authorize" in violation.message for violation in violations)

    clean_root = tmp_path / "clean"
    _write(
        clean_root,
        "backend/src/fairpool/modules/mcp/tools.py",
        "async def list_pools():\n    ...\n\n"
        "async def enter_pool():\n    ...\n\n"
        "async def list_entries():\n    ...\n\n"
        "async def withdraw_entry():\n    ...\n",
    )
    assert _rules(clean_root) == set()


def test_frontend_areas_import_only_through_index(tmp_path: Path) -> None:
    _write(tmp_path, "frontend/src/shared/index.ts", "export const api = 1;\n")
    _write(tmp_path, "frontend/src/shared/api/client.ts", "export const client = 1;\n")
    _write(
        tmp_path,
        "frontend/src/buyer/page.tsx",
        'import { api } from "../shared";\n'
        'import { api as aliased } from "@/shared";\n'
        'import "../shared/index";\n',
    )
    _write(
        tmp_path,
        "frontend/src/buyer/deep.ts",
        'import { client } from "../shared/api/client";\n',
    )
    _write(
        tmp_path,
        "frontend/src/shared/inner.ts",
        'export { api } from "../shared";\n',
    )

    violations = _scan(tmp_path)
    assert len(violations) == 1
    violation = violations[0]
    assert violation.rule == 8
    assert violation.path.as_posix().endswith("frontend/src/buyer/deep.ts")
    assert violation.line == 1


def test_frontend_rule_is_skipped_without_frontend_src(tmp_path: Path) -> None:
    _write(tmp_path, "backend/src/fairpool/domain/money.py", "import dataclasses\n")
    assert _scan(tmp_path) == []


def test_cli_prints_file_line_rule_and_exits_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _write(
        tmp_path,
        "backend/src/fairpool/modules/pools/service.py",
        "from fairpool.adapters.paypal import gateway\n",
    )
    code = check_imports.main(["--root", str(tmp_path)])
    output = capsys.readouterr().out
    assert code == 1
    assert re.search(
        r"backend/src/fairpool/modules/pools/service\.py:1 rule 3 ",
        output,
    )
    assert "import check: 1 violation(s)" in output


def test_cli_exits_zero_on_clean_tree(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _write(tmp_path, "backend/src/fairpool/domain/money.py", "import dataclasses\n")
    code = check_imports.main(["--root", str(tmp_path)])
    output = capsys.readouterr().out
    assert code == 0
    assert "import check: 0 violation(s)" in output
