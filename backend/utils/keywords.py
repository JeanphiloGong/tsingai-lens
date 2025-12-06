from typing import List

import yake


def extract_keywords(text: str, max_keywords: int = 15, lang: str = "zh") -> List[str]:
    kw_extractor = yake.KeywordExtractor(lan=lang, n=3, top=max_keywords)
    keywords = kw_extractor.extract_keywords(text)
    return [kw for kw, score in keywords]
