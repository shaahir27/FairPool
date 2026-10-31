#!/usr/bin/env python3
"""Enforce the import boundaries from docs/scaffold.md section 5.

The checker parses Python imports under ``backend/src/fairpool`` and, when the
frontend exists, TypeScript/JavaScript imports under ``frontend/src``. Missing
directories are skipped so the tool works while the tree is still being built.

Usage (from the repository root)::

    python tools/check_imports.py [--root PATH]

Every violation prints as ``path:line rule N message``. The exit code is 1 if
any violation is found and 0 otherwise.
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "fairpool"

A_MODULES = frozenset({"checkout", "ledger", "webhooks", "reconciler", "fulfillment", "infra"})
B_MODULES = frozenset(
    {
        "identity",
        "catalog",
        "intake",
        "pools",
        "allocation",
        "auction",
        "merchants",
        "search",
        "agentapi",
        "mcp",
        "sim",
        "notify",
    }
)

DOMAIN = f"{PACKAGE}.domain"
AI = f"{PACKAGE}.adapters.ai"
PAYPAL = f"{PACKAGE}.adapters.paypal"
SEARCH = f"{PACKAGE}.adapters.search"
PORTS = f"{PACKAGE}.ports"
MODULES = f"{PACKAGE}.modules"
SIM = f"{MODULES}.sim"
MCP = f"{MODULES}.mcp"
AGENTAPI = f"{MODULES}.agentapi"

A_TARGETS = tuple(f"{MODULES}.{name}" for name in sorted(A_MODULES - {"infra"})) + (
    f"{PACKAGE}.infra",
)
B_TARGETS = tuple(f"{MODULES}.{name}" for name in sorted(B_MODULES))

PAYPAL_IMPORTERS = (
    f"{MODULES}.checkout",
    f"{MODULES}.webhooks",
    f"{MODULES}.reconciler",
    f"{MODULES}.fulfillment",
    f"{PACKAGE}.wiring",
    f"{PACKAGE}.api.routers.checkout",
    f"{PACKAGE}.api.routers.webhooks",
    f"{PACKAGE}.api.routers.admin_ops",
    f"{PACKAGE}.api.routers.health",
    f"{PACKAGE}.api.routers.merchant_fulfillment",
)

SEARCH_FORBIDDEN = (
    PAYPAL,
    f"{MODULES}.ledger",
    f"{MODULES}.checkout",
    AI,
)

PAYMENT_ACTIONS = frozenset({"authorize", "capture", "void", "refund", "charge"})

FRONTEND_SUFFIXES = frozenset({".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"})
FRONTEND_IMPORT_RE = re.compile(
    r"""(?:\bfrom\s*|\bimport\s*\(\s*|\brequire\s*\(\s*|\bimport\s+)(["'])([^"']+)\1"""
)
CAMEL_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
WORD_RE = re.compile(r"[^A-Za-z0-9]+")


@dataclass(frozen=True)
class Violation:
    """One import-boundary violation with enough context for the CLI."""

    path: Path
    line: int
    rule: int
    message: str

    def render(self, root: Path) -> str:
        try:
            relative = self.path.resolve().relative_to(root.resolve())
        except ValueError:
            relative = self.path
        return f"{relative.as_posix()}:{self.line} rule {self.rule} {self.message}"


def _is_under(name: str, prefix: str) -> bool:
    return name == prefix or name.startswith(f"{prefix}.")


def _module_name(path: Path, package_root: Path) -> str:
    relative = path.relative_to(package_root).with_suffix("")
    parts = list(relative.parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join([package_root.name, *parts])


def _resolve_relative(module: str, is_package: bool, level: int) -> list[str] | None:
    parts = module.split(".")
    if not is_package:
        parts = parts[:-1]
    keep = len(parts) - (level - 1)
    if keep <= 0:
        return None
    return parts[:keep]


def _import_targets(tree: ast.AST, module: str, is_package: bool) -> Iterator[tuple[int, str]]:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield node.lineno, alias.name
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base_parts = _resolve_relative(module, is_package, node.level)
                if base_parts is None:
                    continue
                if node.module:
                    base_parts = [*base_parts, *node.module.split(".")]
                base = ".".join(base_parts)
            else:
                base = node.module or ""
            for alias in node.names:
                if not base:
                    continue
                yield node.lineno, base if alias.name == "*" else f"{base}.{alias.name}"


def _group(name: str) -> str | None:
    if any(_is_under(name, target) for target in A_TARGETS):
        return "A"
    if any(_is_under(name, target) for target in B_TARGETS):
        return "B"
    return None


def _is_ai_run_target(target: str) -> bool:
    return any(part in {"ai_run", "ai_runs"} for part in target.split("."))


def _name_tokens(name: str) -> set[str]:
    spaced = CAMEL_RE.sub("_", name)
    return {part.lower() for part in WORD_RE.split(spaced) if part}


def _payment_like(name: str) -> bool:
    tokens = _name_tokens(name)
    if tokens & PAYMENT_ACTIONS:
        return True
    return {"create", "order"} <= tokens


def _check_import(
    path: Path,
    module: str,
    line: int,
    target: str,
) -> Iterator[Violation]:
    top = target.split(".", 1)[0]
    stdlib = top in sys.stdlib_module_names or top == "__future__"

    # Rule 1: domain is pure. cryptography is allowed only in domain/hashing.py.
    if _is_under(module, DOMAIN):
        allowed = (
            stdlib
            or top == "pydantic"
            or _is_under(target, DOMAIN)
            or (
                top == "cryptography" and path.parent.name == "domain" and path.name == "hashing.py"
            )
        )
        if not allowed:
            yield Violation(
                path,
                line,
                1,
                "domain may import only the standard library, pydantic and "
                "fairpool.domain (cryptography only in domain/hashing.py)",
            )

    # Rule 2: the AI adapter sees ports and the AI SDKs, never payment modules.
    if _is_under(module, AI):
        allowed = (
            stdlib
            or top in {"pydantic", "httpx"}
            or _is_under(target, "google.genai")
            or _is_under(target, PORTS)
            or _is_under(target, DOMAIN)
            or _is_under(target, AI)
        )
        if not allowed:
            yield Violation(
                path,
                line,
                2,
                "adapters.ai may import only the standard library, fairpool.ports, "
                "fairpool.domain, google.genai, httpx and pydantic (I2)",
            )

    # Rule 3: only the money modules, wiring, Member A routers and tests may
    # import the PayPal adapter; the adapter imports no fairpool.modules.
    if _is_under(target, PAYPAL) and not _is_under(module, PAYPAL) and not _is_under(module, SIM):
        if not any(_is_under(module, prefix) for prefix in PAYPAL_IMPORTERS):
            yield Violation(
                path,
                line,
                3,
                f"{target} may be imported only by Member A money modules, wiring, "
                "its routers and tests (I2, INT-5)",
            )
    if _is_under(module, PAYPAL) and _is_under(target, MODULES):
        yield Violation(
            path,
            line,
            3,
            f"{PAYPAL} must not import {target} (I2)",
        )

    # Rule 4: simulation uses the fake router, never the PayPal adapter.
    if _is_under(module, SIM) and _is_under(target, PAYPAL):
        yield Violation(
            path,
            line,
            4,
            "modules.sim must not import the PayPal adapter (I12)",
        )

    # Rule 5: the two module groups meet through ports, jobs and HTTP only.
    source_group = _group(module)
    target_group = _group(target)
    if (
        source_group
        and target_group
        and source_group != target_group
        and not _is_under(module, MCP)
        and not _is_under(module, AGENTAPI)
    ):
        yield Violation(
            path,
            line,
            5,
            f"Member {source_group} modules must not import Member {target_group} "
            "modules; use fairpool.ports (scaffold section 5.5)",
        )

    # Rule 6: search retrieval sees public documents, not money or AI-run code.
    if _is_under(module, SEARCH):
        if any(_is_under(target, prefix) for prefix in SEARCH_FORBIDDEN) or _is_ai_run_target(
            target
        ):
            yield Violation(
                path,
                line,
                6,
                "adapters.search must not import PayPal, ledger, checkout or AI-run code (INT-1)",
            )

    # Rule 7: agent-facing modules never reach Member A modules.
    if _is_under(module, MCP) or _is_under(module, AGENTAPI):
        if target_group == "A":
            yield Violation(
                path,
                line,
                7,
                "modules.mcp and modules.agentapi must not import Member A modules (INT-3, INT-5)",
            )


def _decorator_strings(node: ast.AST) -> Iterator[str]:
    for child in ast.walk(node):
        if isinstance(child, ast.Constant) and isinstance(child.value, str):
            yield child.value


def _payment_tools(tree: ast.AST) -> Iterator[tuple[int, str]]:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            if _payment_like(node.name):
                yield node.lineno, node.name
            for decorator in node.decorator_list:
                for value in _decorator_strings(decorator):
                    if _payment_like(value):
                        yield decorator.lineno, value
        elif isinstance(node, ast.Call):
            for keyword in node.keywords:
                if (
                    keyword.arg == "name"
                    and isinstance(keyword.value, ast.Constant)
                    and isinstance(keyword.value.value, str)
                    and _payment_like(keyword.value.value)
                ):
                    yield node.lineno, keyword.value.value
    for statement in tree.body:
        targets: list[ast.expr] = []
        if isinstance(statement, ast.Assign):
            targets = list(statement.targets)
        elif isinstance(statement, ast.AnnAssign):
            targets = [statement.target]
        for target in targets:
            if isinstance(target, ast.Name) and _payment_like(target.id):
                yield statement.lineno, target.id


def _scan_python_file(path: Path, package_root: Path) -> Iterator[Violation]:
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
    except (OSError, SyntaxError) as exc:
        yield Violation(path, 1, 0, f"cannot parse Python source: {exc}")
        return

    module = _module_name(path, package_root)
    is_package = path.name == "__init__.py"
    for line, target in _import_targets(tree, module, is_package):
        yield from _check_import(path, module, line, target)

    if _is_under(module, MCP) or _is_under(module, AGENTAPI):
        for line, name in _payment_tools(tree):
            yield Violation(
                path,
                line,
                7,
                f"modules.mcp and modules.agentapi must expose no payment tools "
                f"(found {name!r}) (INT-3, INT-5)",
            )


def _frontend_area(path: Path, frontend_root: Path, *, source: bool) -> str | None:
    try:
        relative = path.resolve().relative_to(frontend_root.resolve())
    except ValueError:
        return None
    minimum = 2 if source else 1
    if len(relative.parts) < minimum:
        return None
    return relative.parts[0]


def _resolve_frontend_spec(path: Path, frontend_root: Path, specifier: str) -> Path | None:
    specifier = specifier.split("?", 1)[0]
    if specifier.startswith("@/"):
        candidate = frontend_root / specifier[2:]
    elif specifier.startswith("."):
        candidate = path.parent / specifier
    else:
        return None
    candidate = candidate.resolve()
    try:
        candidate.relative_to(frontend_root.resolve())
    except ValueError:
        return None
    return candidate


def _is_area_index(target: Path, frontend_root: Path, area: str) -> bool:
    area_root = (frontend_root / area).resolve()
    index = area_root / "index.ts"
    if target == area_root or target == index:
        return True
    if target.suffix == "" and target.with_suffix(".ts") == index:
        return True
    return False


def _scan_frontend_file(path: Path, frontend_root: Path) -> Iterator[Violation]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        yield Violation(path, 1, 0, f"cannot read frontend source: {exc}")
        return

    source_area = _frontend_area(path, frontend_root, source=True)
    if source_area is None:
        return
    for match in FRONTEND_IMPORT_RE.finditer(text):
        line_start = text.rfind("\n", 0, match.start()) + 1
        if "//" in text[line_start : match.start()]:
            continue
        specifier = match.group(2)
        target = _resolve_frontend_spec(path, frontend_root, specifier)
        if target is None:
            continue
        target_area = _frontend_area(target, frontend_root, source=False)
        if target_area is None or target_area == source_area:
            continue
        if not _is_area_index(target, frontend_root, target_area):
            line = text.count("\n", 0, match.start()) + 1
            yield Violation(
                path,
                line,
                8,
                f"area {source_area!r} may import area {target_area!r} only through "
                f"{target_area}/index.ts (scaffold section 5.8)",
            )


def scan(root: Path) -> list[Violation]:
    """Return every violation under ``root``; missing area directories are skipped."""
    root = root.resolve()
    package_root = root / "backend" / "src" / PACKAGE
    frontend_root = root / "frontend" / "src"
    violations: set[Violation] = set()

    if package_root.is_dir():
        for path in sorted(package_root.rglob("*.py")):
            violations.update(_scan_python_file(path, package_root))

    if frontend_root.is_dir():
        for path in sorted(frontend_root.rglob("*")):
            if path.is_file() and path.suffix in FRONTEND_SUFFIXES:
                violations.update(_scan_frontend_file(path, frontend_root))

    return sorted(
        violations,
        key=lambda violation: (
            violation.path.as_posix(),
            violation.line,
            violation.rule,
            violation.message,
        ),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=REPO_ROOT,
        help="repository root (default: the checkout containing this tool)",
    )
    args = parser.parse_args(argv)
    root = args.root.resolve()

    violations = scan(root)
    for violation in violations:
        print(violation.render(root))
    print(f"import check: {len(violations)} violation(s)")
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
