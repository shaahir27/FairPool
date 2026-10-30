from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_required_paths_exist():
    required = [
        "AGENTS.md",
        "LICENSE",
        "README.md",
        "Makefile",
        ".env.example",
        ".gitignore",
        ".graphifyignore",
        "docs/agents.md",
        "docs/contracts/vectors/fairness_v1.json",
        "backend/pyproject.toml",
        "backend/src/fairpool/__init__.py",
        "backend/src/fairpool/domain/__init__.py",
        "backend/src/fairpool/api/app.py",
        ".codex/skills/graphify/SKILL.md",
        "graphify-out/graph.json",
    ]
    missing = [p for p in required if not (ROOT / p).exists()]
    assert not missing, f"missing: {missing}"


def test_codex_agent_file_and_no_claude_file():
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    assert "docs/00-index.md" in agents and "docs/agents.md" in agents
    assert "## graphify" in agents
    assert not (ROOT / "CLAUDE.md").exists()
    assert not (ROOT / ".claude").exists()


def test_json_files_are_not_ignored():
    lines = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "*.json" not in [line.strip() for line in lines]
