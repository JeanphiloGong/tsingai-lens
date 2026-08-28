from __future__ import annotations

from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
)


class StructuredDocumentProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    doc_type: Literal["experimental", "review", "mixed", "uncertain"] = "uncertain"
    parsing_warnings: list[
        Literal["insufficient_content", "classification_uncertain"]
    ] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    @field_validator("confidence", mode="before")
    @classmethod
    def _normalize_default_confidence(cls, value: object) -> object:
        if value is not None:
            return value
        return cls.model_fields["confidence"].get_default(call_default_factory=True)
