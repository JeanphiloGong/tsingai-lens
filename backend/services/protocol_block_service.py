from __future__ import annotations

import re
from typing import Any
from uuid import uuid4

import pandas as pd

_SYNTHESIS_HINTS = (
    "mix",
    "mixed",
    "dissolve",
    "dissolved",
    "stir",
    "stirred",
    "prepare",
    "prepared",
    "add",
    "added",
    "hydrothermal",
    "solvothermal",
    "fabricat",
    "synthes",
    "blended",
    "加入",
    "混合",
    "搅拌",
    "溶解",
    "制备",
)

_POST_TREATMENT_HINTS = (
    "wash",
    "washed",
    "dry",
    "dried",
    "anneal",
    "annealed",
    "calcine",
    "calcined",
    "cure",
    "cured",
    "sinter",
    "sintered",
    "hot press",
    "cool",
    "quench",
    "filtered",
    "洗涤",
    "干燥",
    "退火",
    "烧结",
    "固化",
    "冷却",
)

_CHARACTERIZATION_HINTS = (
    "xrd",
    "sem",
    "tem",
    "xps",
    "raman",
    "ftir",
    "dsc",
    "tga",
    "xrf",
    "characteriz",
    "analy",
    "表征",
    "显微",
    "光谱",
)

_PROPERTY_TEST_HINTS = (
    "tensile",
    "compression",
    "flexural",
    "hardness",
    "fatigue",
    "wear",
    "corrosion",
    "aging",
    "thermal conductivity",
    "thermal stability",
    "mechanical test",
    "test",
    "tests",
    "performed",
    "property",
    "measured",
    "tested",
    "拉伸",
    "压缩",
    "弯曲",
    "硬度",
    "疲劳",
    "耐蚀",
    "老化",
    "热导",
    "热稳定",
    "性能测试",
)


def build_procedure_blocks(sections: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for _, row in sections.iterrows():
        fragments = _split_into_fragments(str(row.get("text") or ""))
        merged = _merge_fragments(fragments, str(row.get("section_type") or "methods"))
        for order, fragment in enumerate(merged, start=1):
            block_type, keyword_hits, confidence = _classify_fragment(
                fragment["text"],
                str(row.get("section_type") or "methods"),
            )
            if block_type is None:
                continue
            rows.append(
                {
                    "block_id": str(uuid4()),
                    "paper_id": str(row["paper_id"]),
                    "section_id": str(row["section_id"]),
                    "section_type": str(row["section_type"]),
                    "block_type": block_type,
                    "text": fragment["text"],
                    "order": order,
                    "text_unit_ids": list(row.get("text_unit_ids") or []),
                    "sentence_count": _sentence_count(fragment["text"]),
                    "keyword_hits": keyword_hits,
                    "confidence": confidence,
                }
            )
    return pd.DataFrame(
        rows,
        columns=[
            "block_id",
            "paper_id",
            "section_id",
            "section_type",
            "block_type",
            "text",
            "order",
            "text_unit_ids",
            "sentence_count",
            "keyword_hits",
            "confidence",
        ],
    )


def _split_into_fragments(text: str) -> list[str]:
    normalized = text.replace("\r\n", "\n").strip()
    if not normalized:
        return []

    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", normalized) if part.strip()]
    if len(paragraphs) == 1:
        lines = [part.strip() for part in normalized.splitlines() if part.strip()]
        if len(lines) > 1:
            paragraphs = lines

    fragments: list[str] = []
    for paragraph in paragraphs:
        sentences = _split_sentences(paragraph)
        if len(sentences) <= 2:
            fragments.append(paragraph)
            continue
        current: list[str] = []
        for sentence in sentences:
            if current and (_looks_like_new_step(sentence) or len(current) >= 2):
                fragments.append(" ".join(current).strip())
                current = []
            current.append(sentence)
        if current:
            fragments.append(" ".join(current).strip())
    return [fragment for fragment in fragments if fragment]


def _merge_fragments(fragments: list[str], section_type: str) -> list[dict[str, str]]:
    merged: list[dict[str, str]] = []
    for fragment in fragments:
        block_type, _, _ = _classify_fragment(fragment, section_type)
        if not merged or merged[-1]["block_type"] != block_type:
            merged.append({"text": fragment, "block_type": block_type or "other"})
            continue
        merged[-1]["text"] = f"{merged[-1]['text']} {fragment}".strip()
    return merged


def _classify_fragment(text: str, section_type: str) -> tuple[str | None, list[str], float]:
    lowered = text.lower()
    score_map = {
        "synthesis": _score_hits(lowered, _SYNTHESIS_HINTS),
        "post_treatment": _score_hits(lowered, _POST_TREATMENT_HINTS),
        "characterization": _score_hits(lowered, _CHARACTERIZATION_HINTS),
        "property_test": _score_hits(lowered, _PROPERTY_TEST_HINTS),
    }
    if section_type == "characterization":
        score_map["characterization"] += 1

    priority = {
        "property_test": 4,
        "characterization": 3,
        "post_treatment": 2,
        "synthesis": 1,
    }
    winner = max(score_map, key=lambda key: (score_map[key], priority[key]))
    top_score = score_map[winner]
    if top_score <= 0:
        return None, [], 0.0
    total = max(sum(score_map.values()), 1)
    confidence = min(0.99, 0.45 + (top_score / total) * 0.4)
    hits = _matched_keywords(lowered, winner)
    return winner, hits[:8], round(confidence, 3)


def _score_hits(text: str, hints: tuple[str, ...]) -> int:
    return sum(1 for token in hints if token in text)


def _matched_keywords(text: str, block_type: str) -> list[str]:
    lookup = {
        "synthesis": _SYNTHESIS_HINTS,
        "post_treatment": _POST_TREATMENT_HINTS,
        "characterization": _CHARACTERIZATION_HINTS,
        "property_test": _PROPERTY_TEST_HINTS,
    }
    return [token for token in lookup[block_type] if token in text]


def _split_sentences(text: str) -> list[str]:
    return [item.strip() for item in re.split(r"(?<=[。.!?;])\s+", text) if item.strip()]


def _looks_like_new_step(sentence: str) -> bool:
    lowered = sentence.lower()
    return lowered.startswith(("then ", "after ", "subsequently ", "next ", "finally ")) or sentence.startswith(
        ("然后", "随后", "最后")
    )


def _sentence_count(text: str) -> int:
    return len(_split_sentences(text)) or 1
