from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Dict, Optional

import httpx
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import settings
from ..core.feature_flags import list_feature_flags
from .product_service import ProductService
from .rag_index import RAGIndex

logger = logging.getLogger(__name__)


class ProductInsight(BaseModel):
    product: str = Field(..., description="Product matched to the answer")
    summary: str = Field(..., description="Conversational response for the shopper")
    price: float | None = Field(default=None, description="Current product price if relevant")
    highlights: list[str] = Field(default_factory=list, description="Key facts extracted from the catalogue")


class MockLLM:
    """Mock LLM with configurable response variations for workshop testing."""

    RESPONSE_TEMPLATES = [
        "(Mock) Based on your question '{question}', consider: {context_line}",
        "(Mock) Great question about '{question}'! Here's what I found: {context_line}",
        "(Mock) Looking at '{question}', I'd recommend: {context_line}",
        "(Mock) For '{question}', our catalogue suggests: {context_line}",
        "(Mock) Regarding '{question}': {context_line}",
    ]

    def __init__(self, varied: bool = False, seed: int = None):
        self.varied = varied
        self.seed = seed
        self._call_count = 0

    async def run(self, question: str, context: str, mode: str) -> ProductInsight:
        self._call_count += 1

        if context:
            first_line = context.splitlines()[0]
        else:
            first_line = "We offer a curated catalogue of productivity gadgets."

        # Select template based on variation mode
        if self.varied:
            template_idx = (self._call_count + (self.seed or 0)) % len(self.RESPONSE_TEMPLATES)
            template = self.RESPONSE_TEMPLATES[template_idx]
        else:
            template = self.RESPONSE_TEMPLATES[0]

        summary = template.format(question=question, context_line=first_line)

        # Vary highlights if in variation mode
        highlights = [first_line]
        if self.varied and context:
            lines = context.splitlines()[:3]
            highlights = [line for line in lines if line.strip()]

        return ProductInsight(
            product="Catalogue Overview",
            summary=summary,
            price=None,
            highlights=highlights,
        )


def build_prompt_header(question: str, mode: str) -> str:
    """Craft a deterministic header for prompting or logging.

    >>> build_prompt_header("Tell me about headphones", "summary")
    'Mode: summary | Question: Tell me about headphones'
    """
    return f"Mode: {mode} | Question: {question}"


class AIService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.provider = settings.ai_provider
        self.model = settings.ai_model
        self._index = RAGIndex()
        self._mock_llm = MockLLM()
        self._flags: Dict[str, bool] = {}

    async def _load_flags(self) -> Dict[str, bool]:
        """Load workshop feature flags."""
        if not self._flags:
            self._flags = await list_feature_flags(self.session)
        return self._flags

    async def _ensure_index(self) -> None:
        if self._index._index:
            return
        product_service = ProductService(self.session)
        products = await product_service.list_products()
        self._index.build(products)

    async def _call_openai_chat(self, *, question: str, mode: str, context: str) -> ProductInsight:
        """Call an OpenAI-compatible chat completion endpoint directly."""
        if not settings.ai_api_key:
            raise ValueError("Missing AI API key")

        base_url = settings.ai_base_url or "https://api.openai.com/v1"
        headers: dict[str, str] = {"Content-Type": "application/json"}
        params: dict[str, str] | None = None

        is_azure = "azure.com" in base_url.lower()
        if is_azure:
            headers["api-key"] = settings.ai_api_key
            api_version = settings.ai_api_version or "2024-08-01-preview"
            params = {"api-version": api_version}

            deployment_name = self.model
            base_root = base_url.rstrip("/")

            lowered = base_root.lower()
            # Strip common suffixes like /openai or /openai/v1 to normalise the endpoint.
            for suffix in ("/openai/v1", "/openai"):
                if lowered.endswith(suffix):
                    base_root = base_root[: -len(suffix)]
                    lowered = base_root.lower()
                    break

            if "/deployments/" in lowered:
                endpoint = f"{base_root}/chat/completions"
            else:
                endpoint = f"{base_root}/openai/deployments/{deployment_name}/chat/completions"
        else:
            headers["Authorization"] = f"Bearer {settings.ai_api_key}"
            endpoint = f"{base_url.rstrip('/')}/chat/completions"

        has_context = bool(context and context.strip())
        context_snippet = context.strip()[:6000] if has_context else "No matching products were retrieved for this query."
        system_prompt = (
            "You are the helpful Flowline Supply concierge. "
            "Use only the catalogue context provided below as your source of truth. "
            "If the context does not mention a relevant product, clearly state that the item is not currently available "
            "instead of guessing or inventing details. "
            "Respond concisely using the provided context. "
            "Return valid JSON with the shape: "
            '{"product": string, "summary": string, "price": number or null, "highlights": string[]}. '
            "If you are unsure of the price, use null. "
            "Highlights should be short factual bullet strings derived from the context."
        )
        user_prompt = (
            f"Question: {question}\n\n"
            f"Catalogue context:\n{context_snippet}\n\n"
            "If no relevant products appear in the context, respond with JSON indicating the product is unavailable. "
            "Respond with JSON only."
        )

        payload: dict[str, Any] = {
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }

        if not is_azure:
            payload["model"] = self.model
            payload["max_tokens"] = 800
            payload["temperature"] = 0.2
            payload["top_p"] = 0.9
            payload["response_format"] = {"type": "json_object"}
        else:
            payload["max_completion_tokens"] = 800

        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
            response = await client.post(endpoint, headers=headers, params=params, json=payload)
            response.raise_for_status()
            data = response.json()

        try:
            message = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ValueError("Unexpected response payload from AI provider") from exc

        try:
            parsed = json.loads(message)
        except json.JSONDecodeError:
            logger.debug("AI response was not valid JSON, returning fallback summary. raw=%s", message)
            return ProductInsight(
                product="Catalogue Recommendation",
                summary=message.strip(),
                price=None,
                highlights=[context_snippet[:280]],
            )

        price_value = None
        if isinstance(parsed, dict):
            highlights = parsed.get("highlights")
            if isinstance(highlights, list):
                highlights = [str(item) for item in highlights if isinstance(item, (str, int, float))]
            else:
                highlights = []

            price_field = parsed.get("price")
            if isinstance(price_field, (int, float)):
                price_value = float(price_field)
            else:
                try:
                    price_value = float(price_field)
                except (TypeError, ValueError):
                    price_value = None

            return ProductInsight(
                product=str(parsed.get("product") or "Flowline Supply"),
                summary=str(parsed.get("summary") or message).strip(),
                price=price_value,
                highlights=highlights,
            )

        return ProductInsight(product="Flowline Supply", summary=message.strip(), price=None, highlights=[])

    async def ask(self, question: str, mode: str = "summary", provider_override: Optional[str] = None) -> Dict[str, Any]:
        provider = provider_override or self.provider or "mock"

        # Load workshop flags
        flags = await self._load_flags()

        # Workshop: Apply random delay if enabled
        if flags.get("AI_RANDOM_DELAYS"):
            import random
            delay = random.uniform(0.5, 2.0)
            await asyncio.sleep(delay)

        await self._ensure_index()
        context = self._index.get_context(question)

        header = build_prompt_header(question, mode)

        # Workshop: Force deterministic mode if flag is set
        if flags.get("AI_DETERMINISTIC"):
            provider = "mock"

        # Workshop: Configure mock LLM variations
        if provider == "mock" or not settings.ai_api_key:
            varied = flags.get("AI_VARIED_RESPONSES", False)
            self._mock_llm = MockLLM(varied=varied, seed=hash(question) % 1000)

        if provider == "openai" and settings.ai_api_key:
            try:
                insight = await self._call_openai_chat(question=question, mode=mode, context=context)
                return {
                    "question": question,
                    "mode": mode,
                    "provider": provider,
                    "answer": insight.model_dump(),
                    "context_used": context,
                    "prompt_header": header,
                    "workshop_flags": {
                        "deterministic": flags.get("AI_DETERMINISTIC", False),
                        "varied": flags.get("AI_VARIED_RESPONSES", False),
                        "delayed": flags.get("AI_RANDOM_DELAYS", False),
                    },
                }
            except Exception as exc:
                logger.exception("OpenAI request failed, falling back to mock: %s", exc)

        insight = await self._mock_llm.run(question, context, mode)

        return {
            "question": question,
            "mode": mode,
            "provider": "mock",
            "answer": insight.model_dump(),
            "context_used": context,
            "prompt_header": header,
            "workshop_flags": {
                "deterministic": flags.get("AI_DETERMINISTIC", True),
                "varied": flags.get("AI_VARIED_RESPONSES", False),
                "delayed": flags.get("AI_RANDOM_DELAYS", False),
            },
        }
