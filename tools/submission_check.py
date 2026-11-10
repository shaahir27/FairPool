"""Final submission checks (T11X01): report PASS/FAIL/OWNER for every checklist line.

Read-only against git, GitHub, the deployed app and the evidence directory. It never
prints a secret: it only reports whether tracked files contain shapes that look like one.
Two modes: the default reports owner actions as OWNER (not failures); ``--final``
requires the public flip, the active keep-warm workflow and a video link.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
APP_URL = "https://fairpool-api.onrender.com"

#: api.md / deploy/render.yaml, read here rather than guessed from the live app.
EXPECTED_SWITCHES = {
    "PAYMENT_MODE": "authorize_capture",
    "PAYMENT_ROUTER": "single_seller",
    "VAULT_REAL_SAVE_ENABLED": "false",
    "PLATFORM_FEE_ENABLED": "false",
    "PAYPAL_PAYLOAD_LEVEL": "0",
    "WEBHOOKS_ENABLED": "false",
    "BEACON_MODE": "demo",
    "AI_ENABLED": "true",
    "SEARCH_BACKEND": "elastic",
}

SECRET_SHAPES = (
    re.compile(r"fpd_[0-9a-f]{8,}"),
    re.compile(r"fpm_[0-9a-f]{8,}"),
    re.compile(r"AIza[0-9A-Za-z_-]{20,}"),
    re.compile(r"sk-[0-9A-Za-z]{20,}"),
    # A credential in a remote connection string is a leak; the documented loopback
    # test database with the compose defaults is not.
    re.compile(
        r"postgres(?:ql)?(?:\+\w+)?://[^/\s:@]+:[^/\s@]+@"
        r"(?!(?:localhost|127\.0\.0\.1|\[::1\])(?:[:/]|$))"
    ),
)


def run(*command: str, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command, cwd=ROOT, capture_output=True, text=True, timeout=timeout, check=False
    )


def fetch(url: str, timeout: int = 30) -> tuple[int, str]:
    request = urllib.request.Request(url, headers={"User-Agent": "FairPool-submission-check"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            return response.status, response.read(4096).decode("utf-8", "replace")
    except urllib.error.HTTPError as error:
        return error.code, ""
    except Exception as error:  # unreachable host, timeout, DNS
        return 0, type(error).__name__


class Report:
    def __init__(self, final: bool) -> None:
        self.final = final
        self.rows: list[dict[str, Any]] = []
        self.failures = 0

    def add(self, state: str, label: str, detail: str = "") -> None:
        if state == "FAIL":
            self.failures += 1
        print(f"{state:5}  {label}{('  ' + detail) if detail else ''}")
        self.rows.append({"state": state, "check": label, "detail": detail})

    def check(self, ok: bool, label: str, detail: str = "") -> None:
        self.add("PASS" if ok else "FAIL", label, detail)

    def owner(self, label: str, detail: str = "") -> None:
        self.add("OWNER", label, detail)

    def pending_owner(self, ok: bool, label: str, detail: str = "") -> None:
        if ok:
            self.add("PASS", label, detail)
        elif self.final:
            self.add("FAIL", label, detail)
        else:
            self.owner(label, detail)


def git_tags() -> tuple[set[str], set[str]]:
    local = set(run("git", "tag", "-l").stdout.split())
    remote = {
        line.rsplit("refs/tags/", 1)[-1].removesuffix("^{}")
        for line in run("git", "ls-remote", "--tags", "origin").stdout.splitlines()
        if "refs/tags/" in line
    }
    return local, remote


def latest_ci(sha: str) -> dict[str, Any] | None:
    result = run(
        "gh",
        "run",
        "list",
        "--commit",
        sha,
        "--limit",
        "1",
        "--json",
        "databaseId,conclusion,status",
    )
    try:
        rows = json.loads(result.stdout or "[]")
    except json.JSONDecodeError:
        return None
    return rows[0] if rows else None


def deployed_switches() -> dict[str, str]:
    text = (ROOT / "deploy" / "render.yaml").read_text(encoding="utf-8")
    values: dict[str, str] = {}
    for match in re.finditer(r"- key: (\w+)\n\s+value: \"?([^\"\n]+)\"?", text):
        values[match.group(1)] = match.group(2).strip()
    return values


def evidence_statuses() -> list[tuple[str, str, str]]:
    """Every file the release gates require, including the ones that do not exist.

    Globbing the directory would report only present files, so a gate missing most of its
    evidence would read as passed (independent review, finding 1). The gate's own list is
    the source of truth.
    """
    sys.path.insert(0, str(ROOT / "tools"))
    from gate_check import GATE_EVIDENCE

    rows: list[tuple[str, str, str]] = []
    for gate in ("ig-10", "ig-11"):
        directory, required = GATE_EVIDENCE[gate]
        base = ROOT / "docs" / "evidence" / directory
        for name in required:
            path = base / f"{name}.json"
            if not path.exists():
                rows.append((gate, name, "missing"))
                continue
            try:
                status = str(json.loads(path.read_text(encoding="utf-8")).get("status", "?"))
            except json.JSONDecodeError:
                status = "unreadable"
            rows.append((gate, name, status))
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", default="")
    parser.add_argument("--devpost", default="")
    parser.add_argument("--json", default="")
    parser.add_argument("--final", action="store_true")
    args = parser.parse_args()
    report = Report(final=args.final)

    local_tags, remote_tags = git_tags()
    for tag in ("contracts-v1", "rc1", "ig-10"):
        report.pending_owner(
            tag in local_tags and tag in remote_tags, f"tag {tag} exists locally and on origin"
        )

    head = run("git", "rev-parse", "HEAD").stdout.strip()
    ci = latest_ci(head)
    report.pending_owner(
        bool(ci) and ci.get("conclusion") == "success",
        "CI is green on HEAD",
        f"{head[:7]} {ci.get('conclusion') if ci else 'no run'}",
    )

    repo = run("gh", "repo", "view", "--json", "visibility,licenseInfo,url")
    try:
        repo_data = json.loads(repo.stdout or "{}")
    except json.JSONDecodeError:
        repo_data = {}
    public = repo_data.get("visibility") == "PUBLIC"
    report.pending_owner(public, "repository is public")
    report.pending_owner(bool(repo_data.get("licenseInfo")), "a license is detected in About")

    kept = run("gh", "workflow", "list", "--json", "name,state")
    try:
        workflows = {row["name"]: row["state"] for row in json.loads(kept.stdout or "[]")}
    except (json.JSONDecodeError, KeyError, TypeError):
        workflows = {}
    warm = any("warm" in name.lower() and state == "active" for name, state in workflows.items())
    report.pending_owner(warm, "keep-warm workflow is active")

    health, _ = fetch(f"{APP_URL}/health", timeout=90)
    ready, _ = fetch(f"{APP_URL}/ready", timeout=60)
    report.check(
        health == 200 and ready == 200,
        "hosted app answers logged out",
        f"health={health} ready={ready}",
    )

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    report.check(APP_URL in readme, "README names the hosted app")
    report.check("github.com/shaahir27/FairPool" in readme, "README names the repository")
    leaked = [shape.pattern for shape in SECRET_SHAPES if shape.search(readme)]
    report.check(
        not leaked, "README contains no token or connection-string shape", ",".join(leaked)
    )

    if args.video:
        status, _ = fetch(
            "https://www.youtube.com/oembed?format=json&url="
            + urllib.parse.quote(args.video, safe=""),
            timeout=30,
        )
        report.check(
            status == 200 and args.video in readme, "video is public and linked from the README"
        )
    else:
        report.owner("video link (YouTube, public, under three minutes)")

    if args.devpost:
        status, _ = fetch(args.devpost, timeout=30)
        report.check(status == 200, "Devpost page answers", str(status))
    else:
        report.owner("Devpost submission and its confirmation screenshot")

    switches = deployed_switches()
    mismatched = [
        f"{key}={switches.get(key, 'missing')}"
        for key, want in EXPECTED_SWITCHES.items()
        if switches.get(key) != want
    ]
    report.check(not mismatched, "render.yaml records the demo switch values", ",".join(mismatched))

    statuses = evidence_statuses()
    not_passed = [
        f"{gate}/{name}={status}" for gate, name, status in statuses if status != "passed"
    ]
    report.pending_owner(
        not not_passed, "every phase 10/11 evidence file passed", ",".join(not_passed[:8])
    )

    summary = {
        "status": "passed" if report.failures == 0 else "failed",
        "date": "2026-11-10",
        "final_mode": args.final,
        "head": head,
        "failures": report.failures,
        "checks": report.rows,
        "proves": (
            "the mechanical checklist lines: tags, CI, visibility, hosted health, "
            "README shapes, switches and evidence status"
        ),
        "does_not_prove": (
            "the owner-only lines (Devpost submission, its screenshot, the video's "
            "content) or that the deployed app equals HEAD"
        ),
    }
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    verdict = "ALL MECHANICAL CHECKS PASSED"
    if report.failures:
        verdict = f"{report.failures} FAILED"
    print(f"\n{verdict}")
    return 0 if report.failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
