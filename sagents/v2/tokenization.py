"""Text preprocessing for BM25 memory indexes."""

import re


def tokenize_bm25(text: str) -> list[str]:
    normalized = re.sub(r"[^\w\s\u4e00-\u9fff]", " ", text.lower())
    tokens: list[str] = []
    for word in normalized.split():
        if re.search(r"[\u4e00-\u9fff]", word):
            tokens.extend(re.findall(r"[\u4e00-\u9fff]", word))
            tokens.extend(re.findall(r"[a-z]+", word))
        elif len(word) > 1:
            tokens.append(word)
    return tokens
