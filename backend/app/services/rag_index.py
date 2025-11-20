from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, Iterable, List, Tuple


@dataclass
class RAGDocument:
    product_id: int
    name: str
    description: str
    category: str | None
    price: float

    def to_context(self) -> str:
        return (
            f"Product: {self.name}\n"
            f"Category: {self.category or 'General'}\n"
            f"Price: ${self.price:.2f}\n"
            f"Description: {self.description}\n"
        )


class RAGIndex:
    """In-memory retrieval over product descriptions."""

    def __init__(self) -> None:
        self._index: Dict[int, RAGDocument] = {}
        self._token_cache: Dict[int, set[str]] = {}
        self._text_cache: Dict[int, str] = {}

    def build(self, items: Iterable[dict]) -> None:
        self._index = {}
        self._token_cache = {}
        self._text_cache = {}

        for item in items:
            document = RAGDocument(
                product_id=item["id"],
                name=item["name"],
                description=item["description"],
                category=item.get("category"),
                price=item["price"],
            )
            self._index[item["id"]] = document

            text_blob = f"{document.name} {document.description} {document.category or ''}"
            lowered = text_blob.lower()
            self._text_cache[item["id"]] = lowered
            self._token_cache[item["id"]] = set(self._tokenize(lowered))

    @staticmethod
    def _tokenize(value: str) -> List[str]:
        raw_tokens = re.findall(r"[a-z0-9]+", value.lower())
        tokens: List[str] = []
        for token in raw_tokens:
            tokens.append(token)
            normalized = RAGIndex._normalize_token(token)
            if normalized and normalized != token:
                tokens.append(normalized)
        
        # Add bigrams (consecutive pairs) to handle compound words like "head phones" -> "headphones"
        for i in range(len(raw_tokens) - 1):
            bigram = raw_tokens[i] + raw_tokens[i + 1]
            tokens.append(bigram)
            normalized_bigram = RAGIndex._normalize_token(bigram)
            if normalized_bigram and normalized_bigram != bigram:
                tokens.append(normalized_bigram)
        
        return tokens

    @staticmethod
    def _normalize_token(token: str) -> str:
        if len(token) <= 3:
            return token
        if token.endswith("ies") and len(token) > 4:
            return token[:-3] + "y"
        if token.endswith("es") and len(token) > 4 and token[-3:] in {"ses", "xes", "zes", "ches", "shes"}:
            return token[:-2]
        if token.endswith("s") and len(token) > 3:
            return token[:-1]
        return token

    def search(self, query: str, top_k: int = 3) -> List[RAGDocument]:
        tokens = self._tokenize(query)
        if not tokens:
            return []

        token_set = set(tokens)
        phrase = " ".join(tokens)

        scored: List[Tuple[int, RAGDocument]] = []
        for document in self._index.values():
            doc_tokens = self._token_cache.get(document.product_id, set())
            text = self._text_cache.get(document.product_id, "")

            phrase_score = len(phrase) if phrase and phrase in text else 0
            overlap = doc_tokens.intersection(token_set)
            token_score = sum(len(token) for token in overlap)

            name_tokens = set(self._tokenize(document.name))
            token_score += 2 * sum(len(token) for token in name_tokens.intersection(token_set))

            score = phrase_score + token_score
            if score > 0:
                scored.append((score, document))

        scored.sort(key=lambda item: item[0], reverse=True)
        return [doc for _, doc in scored[:top_k]]

    def get_context(self, query: str, top_k: int = 3) -> str:
        documents = self.search(query, top_k=top_k)
        if not documents:
            return ""
        return "\n---\n".join(doc.to_context() for doc in documents)
