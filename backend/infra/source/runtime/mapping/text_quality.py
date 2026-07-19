from __future__ import annotations

import re
from typing import Any


def normalize_display_text(value: Any) -> str | None:
    if value is None:
        return None
    text = " ".join(str(value).replace("\ufffd", " ").strip().split())
    return text or None


def is_garbled_pdf_text(text: str) -> bool:
    normalized = normalize_display_text(text)
    if not normalized or len(normalized) < 16:
        return False
    if any(0x80 <= ord(char) <= 0x9F for char in normalized):
        return True
    if "\x00" in normalized:
        return True
    replacement_count = str(text or "").count("\ufffd")
    if replacement_count and replacement_count / max(len(str(text)), 1) >= 0.08:
        return True
    words = re.findall(r"[A-Za-z0-9]{4,}", normalized)
    if not words:
        return False
    suspicious_words = sum(1 for word in words if _is_garbled_word(word))
    suspicious_ratio = suspicious_words / len(words)
    alpha_chars = sum(1 for char in normalized if char.isalpha())
    vowels = sum(1 for char in normalized.casefold() if char in "aeiou")
    vowel_ratio = vowels / alpha_chars if alpha_chars else 0
    return suspicious_ratio >= 0.65 or (
        suspicious_ratio >= 0.45 and vowel_ratio < 0.34
    )


def _is_garbled_word(word: str) -> bool:
    letters = [char for char in word if char.isalpha()]
    if len(letters) < 4:
        return False
    uppercase_count = sum(1 for char in letters if char.isupper())
    digit_count = sum(1 for char in word if char.isdigit())
    vowel_count = sum(1 for char in word.casefold() if char in "aeiou")
    uppercase_ratio = uppercase_count / len(letters)
    vowel_ratio = vowel_count / len(letters)
    return (
        digit_count > 0
        or uppercase_ratio >= 0.55
        or vowel_ratio <= 0.18
    )
