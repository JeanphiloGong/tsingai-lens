from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from uuid import uuid4

import pandas as pd

from application.derived.protocol.normalize_service import ProtocolNormalizeService
from application.derived.protocol.validate_service import ProtocolValidateService


_FORMULA_RE = re.compile(r"\b[A-Z][a-z]?\d{0,3}(?:[A-Z][a-z]?\d{0,3})+\b")
_ACTION_PATTERNS = {
    "mix": ("mix", "mixed", "mixing", "blend", "blended", "stir together", "混合"),
    "stir": ("stir", "stirred", "stirring", "agitate", "搅拌"),
    "heat": ("heat", "heated", "heating", "加热"),
    "anneal": ("anneal", "annealed", "annealing", "退火"),
    "calcine": ("calcine", "calcined", "calcination", "煅烧"),
    "dry": ("dry", "dried", "drying", "干燥"),
    "wash": ("wash", "washed", "washing", "rinse", "washed with", "洗涤"),
    "filter": ("filter", "filtered", "filtering", "过滤"),
    "press": ("press", "pressed", "pressing", "压制"),
    "sinter": ("sinter", "sintered", "sintering", "烧结"),
    "dissolve": ("dissolve", "dissolved", "dissolving", "溶解"),
    "add": ("add", "added", "adding", "加入"),
    "cool": ("cool", "cooled", "cooling", "冷却"),
    "characterize": ("characterized", "characterised", "measured", "tested", "表征", "测试"),
}
_CHARACTERIZATION_HINTS = {
    "XRD": re.compile(r"\bXRD\b|x-ray diffraction", re.IGNORECASE),
    "SEM": re.compile(r"\bSEM\b|scanning electron microscopy", re.IGNORECASE),
    "TEM": re.compile(r"\bTEM\b|transmission electron microscopy", re.IGNORECASE),
    "XPS": re.compile(r"\bXPS\b", re.IGNORECASE),
    "Raman": re.compile(r"\bRaman\b", re.IGNORECASE),
    "DSC": re.compile(r"\bDSC\b", re.IGNORECASE),
    "TGA": re.compile(r"\bTGA\b", re.IGNORECASE),
    "Tensile": re.compile(r"tensile|拉伸", re.IGNORECASE),
    "Fatigue": re.compile(r"fatigue|疲劳", re.IGNORECASE),
}
_CONTROL_PATTERNS = {
    "baseline": re.compile(r"\bbaseline\b|\breference\b|基线|参考样", re.IGNORECASE),
    "blank": re.compile(r"\bblank\b|空白", re.IGNORECASE),
    "untreated": re.compile(r"\buntreated\b|未处理", re.IGNORECASE),
    "without_additive": re.compile(r"\bwithout\b|无添加|不加", re.IGNORECASE),
}
_MATERIAL_HINTS = re.compile(
    r"\b(?:solution|powder|resin|matrix|filler|composite|sample|precursor)\b|"
    r"(?:溶液|粉末|树脂|基体|填料|复合材料|样品|前驱体)",
    re.IGNORECASE,
)
_PURPOSE_RE = re.compile(r"\b(?:to|for)\b\s+(.+)$", re.IGNORECASE)
_PURPOSE_CN_RE = re.compile(r"(?:以便|用于|为了)(.+)$")
_OUTPUT_RE = re.compile(
    r"\b(?:yielded|yielding|obtained|obtain|produced|produce|formed|form)\b\s+(.+)$",
    re.IGNORECASE,
)
_OUTPUT_CN_RE = re.compile(r"(?:得到|获得|形成)(.+)$")
_TEMP_OR_DURATION_HINT = re.compile(
    r"(?:°\s?C|℃|\bK\b|\bday\b|\bdays\b|\bh\b|\bhr\b|\bhrs\b|\bmin\b|\bmins\b|\bovernight\b|过夜|室温)",
    re.IGNORECASE,
)


class ProtocolExtractService:
    """Extract protocol-like steps from procedure blocks."""

    def __init__(
        self,
        normalizer: ProtocolNormalizeService | None = None,
        validator: ProtocolValidateService | None = None,
    ):
        self.normalizer = normalizer or ProtocolNormalizeService()
        self.validator = validator or ProtocolValidateService()

    def extract_steps(self, procedure_blocks: pd.DataFrame) -> list[dict[str, Any]]:
        self._validate_input_frame(procedure_blocks)
        steps: list[dict[str, Any]] = []
        paper_counters: dict[str, int] = {}

        ordered = procedure_blocks.copy()
        for column in ("paper_id", "section_id", "order", "block_id"):
            if column not in ordered.columns:
                ordered[column] = None
        ordered = ordered.sort_values(
            by=["paper_id", "section_id", "order", "block_id"],
            na_position="last",
        )

        for _, block in ordered.iterrows():
            text = str(block.get("text") or "").strip()
            if not text:
                continue
            paper_id = str(block.get("paper_id") or "unknown")
            for sentence in self._split_sentences(text):
                if not self._is_candidate(sentence):
                    continue
                paper_counters[paper_id] = paper_counters.get(paper_id, 0) + 1
                step = {
                    "step_id": str(uuid4()),
                    "paper_id": paper_id,
                    "section_id": self._optional_str(block.get("section_id")),
                    "block_id": self._optional_str(block.get("block_id")),
                    "block_type": self._optional_str(block.get("block_type")),
                    "order": paper_counters[paper_id],
                    "action": self._infer_action(sentence),
                    "raw_text": sentence,
                    "materials": self._extract_materials(sentence),
                    "conditions": self.normalizer.normalize_conditions(sentence),
                    "purpose": self._extract_purpose(sentence),
                    "expected_output": self._extract_expected_output(sentence),
                    "characterization": self._extract_characterization(sentence),
                    "controls": self._extract_controls(sentence),
                    "evidence_refs": [
                        {
                            "paper_id": paper_id,
                            "section_id": self._optional_str(block.get("section_id")),
                            "block_id": self._optional_str(block.get("block_id")),
                            "quote_span": sentence[:240],
                        }
                    ],
                    "confidence_score": self._score_sentence(sentence),
                }
                steps.append(self.validator.validate_step(step))
        return steps

    def build_protocol_steps_table(self, procedure_blocks: pd.DataFrame) -> pd.DataFrame:
        return self.validator.to_parquet_frame(self.extract_steps(procedure_blocks))

    def write_protocol_steps_parquet(
        self,
        procedure_blocks: pd.DataFrame,
        output_path: str | Path,
    ) -> Path:
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        self.build_protocol_steps_table(procedure_blocks).to_parquet(output, index=False)
        return output

    def _validate_input_frame(self, procedure_blocks: pd.DataFrame) -> None:
        required = {"block_id", "text"}
        missing = sorted(required - set(procedure_blocks.columns))
        if missing:
            raise ValueError(f"procedure_blocks missing columns: {', '.join(missing)}")

    def _split_sentences(self, text: str) -> list[str]:
        parts = re.split(r"[。！？;.!?\n]+", text)
        return [part.strip() for part in parts if part and part.strip()]

    def _is_candidate(self, sentence: str) -> bool:
        if _TEMP_OR_DURATION_HINT.search(sentence):
            return True
        if any(
            self._matches_alias(sentence, alias)
            for aliases in _ACTION_PATTERNS.values()
            for alias in aliases
        ):
            return True
        if any(pattern.search(sentence) for pattern in _CHARACTERIZATION_HINTS.values()):
            return True
        return False

    def _infer_action(self, sentence: str) -> str:
        for action, aliases in _ACTION_PATTERNS.items():
            if any(self._matches_alias(sentence, alias) for alias in aliases):
                return action
        return "observe"

    def _extract_materials(self, sentence: str) -> list[dict[str, Any]]:
        materials: list[dict[str, Any]] = []
        seen: set[str] = set()
        for formula in _FORMULA_RE.findall(sentence):
            if formula in seen:
                continue
            seen.add(formula)
            materials.append({"name": formula, "formula": formula, "role": "material"})

        match = _MATERIAL_HINTS.search(sentence)
        if match:
            name = match.group(0)
            if name.lower() not in seen:
                materials.append({"name": name, "formula": None, "role": "material"})
        return materials

    def _extract_characterization(self, sentence: str) -> list[dict[str, Any]]:
        items = []
        for method, pattern in _CHARACTERIZATION_HINTS.items():
            if pattern.search(sentence):
                items.append({"method": method})
        return items

    def _extract_controls(self, sentence: str) -> list[dict[str, Any]]:
        items = []
        for control_type, pattern in _CONTROL_PATTERNS.items():
            if pattern.search(sentence):
                items.append({"control_type": control_type, "description": sentence[:180]})
        return items

    def _extract_purpose(self, sentence: str) -> str | None:
        match = _PURPOSE_RE.search(sentence)
        if match:
            return match.group(1).strip()[:240]
        match = _PURPOSE_CN_RE.search(sentence)
        if match:
            return match.group(1).strip()[:240]
        return None

    def _extract_expected_output(self, sentence: str) -> str | None:
        match = _OUTPUT_RE.search(sentence)
        if match:
            return match.group(1).strip()[:240]
        match = _OUTPUT_CN_RE.search(sentence)
        if match:
            return match.group(1).strip()[:240]
        return None

    def _score_sentence(self, sentence: str) -> float:
        score = 0.25
        action = self._infer_action(sentence)
        if action != "observe":
            score += 0.25
        conditions = self.normalizer.normalize_conditions(sentence)
        if conditions["temperature"]["status"] == "reported":
            score += 0.2
        elif conditions["temperature"]["status"] == "ambiguous":
            score += 0.1
        if conditions["duration"]["status"] == "reported":
            score += 0.2
        elif conditions["duration"]["status"] == "ambiguous":
            score += 0.1
        if self._extract_characterization(sentence):
            score += 0.1
        return max(0.0, min(1.0, score))

    def _optional_str(self, value: Any) -> str | None:
        if value is None:
            return None
        text = " ".join(str(value).split())
        return text or None

    def _matches_alias(self, sentence: str, alias: str) -> bool:
        if re.search(r"[A-Za-z]", alias):
            return re.search(rf"\b{re.escape(alias.lower())}\b", sentence.lower()) is not None
        return alias in sentence
