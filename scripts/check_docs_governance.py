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
REQUIRED_FIELDS = [
    "id",
    "title",
    "type",
    "level",
    "domain",
    "status",
    "owner",
    "created_at",
    "updated_at",
]
ALLOWED_TYPES = {
    "policy",
    "architecture",
    "spec",
    "guide",
    "runbook",
    "rfc",
    "adr",
    "postmortem",
    "research-note",
}
ALLOWED_LEVELS = {"system", "domain", "module", "component"}
ALLOWED_STATUSES = {
    "draft",
    "review",
    "accepted",
    "implemented",
    "active",
    "deprecated",
    "superseded",
    "archived",
}
ALLOWED_DOMAINS = {"shared", "backend", "frontend", "ai", "ops", "research"}
DATE_KEYS = {"created_at", "updated_at", "last_verified_at", "review_by"}
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
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
    return sorted(docs)


def parse_front_matter(path: Path) -> tuple[dict[str, str], list[str]]:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    if len(lines) < 3 or lines[0].strip() != "---":
        return {}, ["missing front matter block"]

    metadata: dict[str, str] = {}
    errors: list[str] = []
    in_block = True
    for idx, line in enumerate(lines[1:], start=2):
        stripped = line.strip()
        if stripped == "---":
            in_block = False
            break
        if not line or line.startswith("  - ") or line.startswith("- "):
            continue
        if line.startswith(" "):
            continue
        if ":" not in line:
            errors.append(f"invalid front matter line {idx}: {line}")
            continue
        key, value = line.split(":", 1)
        metadata[key.strip()] = value.strip()

    if in_block:
        errors.append("front matter block is not closed")
    return metadata, errors


def validate_front_matter(path: Path) -> list[str]:
    metadata, errors = parse_front_matter(path)
    if errors:
        return [f"{path.relative_to(REPO_ROOT)}: {error}" for error in errors]

    problems: list[str] = []
    for field in REQUIRED_FIELDS:
        if not metadata.get(field):
            problems.append(f"missing required field `{field}`")

    doc_type = metadata.get("type", "")
    if doc_type and doc_type not in ALLOWED_TYPES:
        problems.append(f"invalid `type`: {doc_type}")

    level = metadata.get("level", "")
    if level and level not in ALLOWED_LEVELS:
        problems.append(f"invalid `level`: {level}")

    status = metadata.get("status", "")
    if status and status not in ALLOWED_STATUSES:
        problems.append(f"invalid `status`: {status}")

    domain = metadata.get("domain", "")
    if domain and domain not in ALLOWED_DOMAINS:
        problems.append(f"invalid `domain`: {domain}")

    for key in DATE_KEYS:
        value = metadata.get(key)
        if value and not DATE_RE.fullmatch(value):
            problems.append(f"`{key}` must use YYYY-MM-DD: {value}")

    return [f"{path.relative_to(REPO_ROOT)}: {problem}" for problem in problems]


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

    for path in governed_docs:
        errors.extend(validate_front_matter(path))

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
