"""Model discovery and ranking for AI providers."""

import re
from dataclasses import dataclass
from enum import Enum

import httpx
import structlog

log = structlog.get_logger()


class Provider(str, Enum):
    """Supported AI providers."""

    OPENROUTER = "openrouter"
    GEMINI = "gemini"


@dataclass
class ModelInfo:
    """Information about an AI model."""

    id: str
    name: str
    provider: Provider
    context_length: int
    is_free: bool
    rank_score: float  # Higher = better quality estimate

    def __str__(self) -> str:
        free_tag = " (free)" if self.is_free else ""
        return f"{self.name}{free_tag}"


class ModelRegistry:
    """Registry for discovering and managing AI models."""

    # Known good free models as fallback
    DEFAULT_FREE_MODELS = [
        ModelInfo(
            id="meta-llama/llama-3.2-3b-instruct:free",
            name="Llama 3.2 3B",
            provider=Provider.OPENROUTER,
            context_length=131072,
            is_free=True,
            rank_score=0.03,
        ),
        ModelInfo(
            id="google/gemma-2-9b-it:free",
            name="Gemma 2 9B",
            provider=Provider.OPENROUTER,
            context_length=8192,
            is_free=True,
            rank_score=0.09,
        ),
    ]

    @classmethod
    async def fetch_openrouter_models(
        cls, api_key: str | None = None
    ) -> list[ModelInfo]:
        """Fetch and rank models from OpenRouter (fresh each call).

        Args:
            api_key: Optional API key for authenticated requests.

        Returns:
            List of ModelInfo sorted by rank_score (best first).
        """
        try:
            async with httpx.AsyncClient() as client:
                headers = {}
                if api_key:
                    headers["Authorization"] = f"Bearer {api_key}"

                response = await client.get(
                    "https://openrouter.ai/api/v1/models",
                    headers=headers,
                    timeout=30.0,
                )
                response.raise_for_status()
                data = response.json()["data"]

            # Build price map for ranking
            price_map: dict[str, float] = {}
            for m in data:
                try:
                    # Cost per 1M tokens
                    price = float(m["pricing"]["prompt"]) * 1_000_000
                    price_map[m["id"]] = price
                except (KeyError, ValueError):
                    continue

            models: list[ModelInfo] = []
            for m in data:
                try:
                    prompt_cost = float(m["pricing"]["prompt"])
                    completion_cost = float(m["pricing"]["completion"])
                except (KeyError, ValueError):
                    continue

                is_free = prompt_cost == 0 and completion_cost == 0

                # Calculate rank score
                rank_score = cls._calculate_rank_score(m["id"], price_map)

                models.append(
                    ModelInfo(
                        id=m["id"],
                        name=m.get("name", m["id"]),
                        provider=Provider.OPENROUTER,
                        context_length=m.get("context_length", 4096),
                        is_free=is_free,
                        rank_score=rank_score,
                    )
                )

            # Sort by rank_score descending
            models.sort(key=lambda x: x.rank_score, reverse=True)

            log.info(
                "openrouter_models_fetched",
                total=len(models),
                free=len([m for m in models if m.is_free]),
            )
            return models

        except Exception as e:
            log.warning("openrouter_fetch_failed", error=str(e))
            return cls.DEFAULT_FREE_MODELS

    @classmethod
    def _calculate_rank_score(cls, model_id: str, price_map: dict[str, float]) -> float:
        """Calculate rank score for a model.

        Uses two strategies:
        1. Price of paid sibling (higher = better quality)
        2. Parameter count from model name (70b > 7b)

        Args:
            model_id: The model ID.
            price_map: Map of model_id -> price per 1M tokens.

        Returns:
            Rank score (higher = better).
        """
        # Strategy 1: Find paid sibling price
        clean_id = model_id.replace(":free", "")
        shadow_value = price_map.get(clean_id, 0)

        # Strategy 2: Parameter count heuristic
        if shadow_value == 0:
            match = re.search(r"(\d+)b", model_id.lower())
            if match:
                shadow_value = int(match.group(1)) / 100

        return shadow_value

    @classmethod
    async def get_free_models(
        cls, api_key: str | None = None, limit: int = 20
    ) -> list[ModelInfo]:
        """Get top free models from OpenRouter.

        Args:
            api_key: Optional API key.
            limit: Maximum models to return.

        Returns:
            List of free models sorted by quality.
        """
        all_models = await cls.fetch_openrouter_models(api_key)
        free_models = [m for m in all_models if m.is_free]
        return free_models[:limit]

    @classmethod
    def get_gemini_models(cls) -> list[ModelInfo]:
        """Get available Gemini models.

        Returns:
            List of Gemini models.
        """
        # Static list of commonly available Gemini models
        return [
            ModelInfo(
                id="gemini-2.0-flash-exp",
                name="Gemini 2.0 Flash (Experimental)",
                provider=Provider.GEMINI,
                context_length=1_000_000,
                is_free=True,  # Free tier available
                rank_score=2.0,
            ),
            ModelInfo(
                id="gemini-2.0-flash",
                name="Gemini 2.0 Flash",
                provider=Provider.GEMINI,
                context_length=1_000_000,
                is_free=True,
                rank_score=1.9,
            ),
            ModelInfo(
                id="gemini-2.0-flash-lite",
                name="Gemini 2.0 Flash Lite",
                provider=Provider.GEMINI,
                context_length=1_000_000,
                is_free=True,
                rank_score=1.5,
            ),
            ModelInfo(
                id="gemini-1.5-flash",
                name="Gemini 1.5 Flash",
                provider=Provider.GEMINI,
                context_length=1_000_000,
                is_free=True,
                rank_score=1.0,
            ),
        ]

    @classmethod
    async def get_all_available_models(
        cls,
        openrouter_key: str | None = None,
        gemini_key: str | None = None,
        free_only: bool = True,
    ) -> list[ModelInfo]:
        """Get all available models across providers.

        Args:
            openrouter_key: OpenRouter API key.
            gemini_key: Gemini API key.
            free_only: Only return free models.

        Returns:
            Combined list of models sorted by rank.
        """
        models: list[ModelInfo] = []

        if openrouter_key:
            or_models = await cls.fetch_openrouter_models(openrouter_key)
            if free_only:
                or_models = [m for m in or_models if m.is_free]
            models.extend(or_models)

        if gemini_key:
            g_models = cls.get_gemini_models()
            if free_only:
                g_models = [m for m in g_models if m.is_free]
            models.extend(g_models)

        # Sort by rank
        models.sort(key=lambda x: x.rank_score, reverse=True)
        return models

    @classmethod
    def find_model_in_gemini(cls, model_id: str) -> ModelInfo | None:
        """Find a model by ID in Gemini models.

        Args:
            model_id: The model ID to find.

        Returns:
            ModelInfo or None.
        """
        for m in cls.get_gemini_models():
            if m.id == model_id:
                return m
        return None

    @classmethod
    async def find_model(
        cls, model_id: str, openrouter_key: str | None = None
    ) -> ModelInfo | None:
        """Find a model by ID (checks Gemini static list and fetches OpenRouter).

        Args:
            model_id: The model ID to find.
            openrouter_key: OpenRouter API key for live lookup.

        Returns:
            ModelInfo or None.
        """
        # Check Gemini models first (static, fast)
        gemini_model = cls.find_model_in_gemini(model_id)
        if gemini_model:
            return gemini_model

        # Check OpenRouter if key provided
        if openrouter_key:
            models = await cls.fetch_openrouter_models(openrouter_key)
            for m in models:
                if m.id == model_id:
                    return m

        return None
