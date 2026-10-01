"""Domain rules must remain usable without application or infrastructure imports."""

import ast
import subprocess
import sys
from pathlib import Path


def test_domain_imports_only_domain_and_general_purpose_libraries() -> None:
    root = Path(__file__).resolve().parents[3] / "domain"
    forbidden = {
        "application",
        "infra",
        "controllers",
        "sqlalchemy",
        "pydantic",
        "fastapi",
    }
    violations = []
    for path in root.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            modules = []
            if isinstance(node, ast.ImportFrom) and node.module:
                modules = [node.module]
            elif isinstance(node, ast.Import):
                modules = [item.name for item in node.names]
            for module in modules:
                if module.split(".")[0] in forbidden:
                    violations.append(
                        f"{path.relative_to(root)}:{node.lineno}: {module}"
                    )
    assert not violations, "\n".join(violations)


def test_chat_and_feedback_can_start_in_a_fresh_interpreter() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import application.chat.capability_policy; import application.feedback",
        ],
        cwd=Path(__file__).resolve().parents[3],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
