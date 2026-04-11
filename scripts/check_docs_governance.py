#!/usr/bin/env python3
from __future__ import annotations

import re
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
GOVERNED_DIRS = [
    REPO_ROOT / "docs" / "05-policies",
    REPO_ROOT / "docs" / "10-rfcs",
    REPO_ROOT / "docs" / "20-adrs",
    REPO_ROOT / "docs" / "30-architecture",
    REPO_ROOT / "docs" / "40-specs",
    REPO_ROOT / "docs" / "50-guides",
    REPO_ROOT / "docs" / "60-runbooks",
    REPO_ROOT / "docs" / "70-postmortems",
    REPO_ROOT / "docs" / "90-archive",
    REPO_ROOT / "docs" / "research",
    REPO_ROOT / "backend" / "docs",
    REPO_ROOT / "frontend" / "docs",
]
DOCS_PATHS = [
    REPO_ROOT / "docs",
    REPO_ROOT / "backend" / "docs",
    REPO_ROOT / "frontend" / "docs",
]
NODE_LOCAL_DOC_FILES = [
    REPO_ROOT / "README.md",
    REPO_ROOT / "backend" / "README.md",
    REPO_ROOT / "frontend" / "README.md",
    REPO_ROOT / "backend" / "api" / "README.md",
    REPO_ROOT / "backend" / "application" / "README.md",
    REPO_ROOT / "backend" / "retrieval" / "README.md",
    REPO_ROOT / "backend" / "retrieval" / "index" / "README.md",
    REPO_ROOT / "backend" / "retrieval" / "query" / "README.md",
    REPO_ROOT / "backend" / "infra" / "persistence" / "README.md",
    REPO_ROOT / "backend" / "tests" / "README.md",
    REPO_ROOT / "frontend" / "src" / "routes" / "_shared" / "README.md",
    REPO_ROOT / "frontend" / "src" / "routes" / "collections" / "README.md",
]
LINK_RE = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
SUSPICIOUS_NAME_RE = re.compile(r"(password|secret|credential)", re.IGNORECASE)
HIGH_SIGNAL_SECRET_PATTERNS = [
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"ghp_[A-Za-z0-9]{30,}"),
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
]


def iter_governed_markdown() -> list[Path]:
    docs: list[Path] = []
    for doc_dir in GOVERNED_DIRS:
        if not doc_dir.exists():
            continue
        for path in sorted(doc_dir.rglob("*.md")):
            if path.name == "README.md":
                continue
            docs.append(path)
    return docs


def iter_all_docs_markdown() -> list[Path]:
    docs: set[Path] = set()
    for doc_dir in DOCS_PATHS:
        if not doc_dir.exists():
            continue
        docs.update(doc_dir.rglob("*.md"))
    for path in NODE_LOCAL_DOC_FILES:
        if path.exists():
            docs.add(path)
    return sorted(docs)


def validate_links(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    problems: list[str] = []
    for match in LINK_RE.finditer(text):
        target = match.group(1).strip()
        if (
            not target
            or target.startswith("#")
            or "://" in target
            or target.startswith("mailto:")
        ):
            continue
        raw_target = target.split("#", 1)[0]
        if not raw_target:
            continue
        resolved = (path.parent / raw_target).resolve()
        if not resolved.exists():
            problems.append(
                f"{path.relative_to(REPO_ROOT)}: broken local link `{target}`"
            )
    return problems


def validate_docs_paths() -> list[str]:
    problems: list[str] = []
    for docs_root in DOCS_PATHS:
        if not docs_root.exists():
            continue
        for path in sorted(docs_root.rglob("*")):
            if path.is_dir():
                continue
            rel = path.relative_to(REPO_ROOT)
            if SUSPICIOUS_NAME_RE.search(path.name):
                problems.append(
                    f"{rel}: suspicious filename in docs path; remove committed secrets"
                )
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for pattern in HIGH_SIGNAL_SECRET_PATTERNS:
                if pattern.search(text):
                    problems.append(
                        f"{rel}: high-signal secret pattern matched `{pattern.pattern}`"
                    )
    return problems


def main() -> int:
    errors: list[str] = []

    governed_docs = iter_governed_markdown()
    all_docs = iter_all_docs_markdown()

    for path in all_docs:
        errors.extend(validate_links(path))

    errors.extend(validate_docs_paths())

    if errors:
        print("Docs governance check failed:\n", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    print(
        "Docs governance check passed for "
        f"{len(governed_docs)} governed docs and {len(all_docs)} markdown files."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
