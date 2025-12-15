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
    GROQ = "groq"
    CEREBRAS = "cerebras"


@dataclass
class ModelInfo:
    """Information about an AI model."""

    id: str
    name: str
    provider: Provider
    context_length: int
    is_free: bool
    rank_score: float  # Higher = better quality estimate
    supports_tools: bool = True  # Whether model supports function calling

    def __str__(self) -> str:
        free_tag = " (free)" if self.is_free else ""
        return f"{self.name}{free_tag}"


class ModelRegistry:
    """Registry for discovering and managing AI models."""

    # Keywords in description that indicate tool support
    TOOL_KEYWORDS = ["tool use", "function calling", "tools", "fc", "function-calling"]

    # Known model families that ALWAYS support tools (even if API doesn't say so)
    KNOWN_TOOL_FAMILIES = [
        "gpt-4", "gpt-3.5", "gpt-oss",
        "claude-3", "claude-2",
        "gemini-1.5", "gemini-2",
        "llama-3.1", "llama-3.2", "llama-3.3",
        "qwen-2.5", "qwen3",
        "mistral-large", "mistral-small", "mistral-medium",
        "deepseek-v3", "deepseek-chat",
        "command-r",
    ]

    # Known good free models as fallback (with tool support)
    DEFAULT_FREE_MODELS = [
        ModelInfo(
            id="meta-llama/llama-3.2-3b-instruct:free",
            name="Llama 3.2 3B",
            provider=Provider.OPENROUTER,
            context_length=131072,
            is_free=True,
            rank_score=0.03,
            supports_tools=False,  # Small model, limited tool support
        ),
        ModelInfo(
            id="google/gemma-2-9b-it:free",
            name="Gemma 2 9B",
            provider=Provider.OPENROUTER,
            context_length=8192,
            is_free=True,
            rank_score=0.09,
            supports_tools=False,  # May not reliably support tools
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

                # Check if model supports tools (function calling) - 3 methods
                supports_tools = cls._detect_tool_support(m)

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
                        supports_tools=supports_tools,
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

    # Priority providers - these get a significant boost
    PRIORITY_PROVIDERS = {
        "x-ai": 100.0,       # Grok
        "google": 90.0,      # Gemini
        "openai": 85.0,      # OpenAI
        "anthropic": 80.0,   # Claude
        "meta-llama": 50.0,  # Llama (very capable)
        "deepseek": 45.0,    # DeepSeek (strong reasoning)
        "mistralai": 40.0,   # Mistral
        "qwen": 35.0,        # Qwen
    }

    @classmethod
    def _calculate_rank_score(cls, model_id: str, price_map: dict[str, float]) -> float:
        """Calculate rank score for a model.

        Uses three strategies:
        1. Priority provider boost (Grok, Gemini, OpenAI, Claude first)
        2. Price of paid sibling (higher = better quality)
        3. Parameter count from model name (70b > 7b)

        Args:
            model_id: The model ID.
            price_map: Map of model_id -> price per 1M tokens.

        Returns:
            Rank score (higher = better).
        """
        score = 0.0

        # Strategy 1: Priority provider boost
        model_lower = model_id.lower()
        for provider, boost in cls.PRIORITY_PROVIDERS.items():
            if provider in model_lower or model_lower.startswith(f"{provider}/"):
                score += boost
                break

        # Strategy 2: Find paid sibling price
        clean_id = model_id.replace(":free", "")
        shadow_value = price_map.get(clean_id, 0)
        score += shadow_value

        # Strategy 3: Parameter count heuristic
        match = re.search(r"(\d+)b", model_id.lower())
        if match:
            param_count = int(match.group(1))
            # Scale: 70b = 0.7, 405b = 4.05
            score += param_count / 100

        return score

    @classmethod
    def _detect_tool_support(cls, model_data: dict) -> bool:
        """Detect if a model supports tool/function calling.

        Uses three methods:
        1. Check supported_parameters field from API
        2. Check description for tool-related keywords
        3. Check if model belongs to known tool-supporting family

        Args:
            model_data: Raw model data from OpenRouter API.

        Returns:
            True if model likely supports tools.
        """
        model_id = model_data.get("id", "").lower()

        # Method 1: API says it supports tools
        supported_params = model_data.get("supported_parameters", [])
        if "tools" in supported_params or "functions" in supported_params:
            return True

        # Method 2: Description mentions tool support
        description = model_data.get("description", "").lower()
        if any(keyword in description for keyword in cls.TOOL_KEYWORDS):
            return True

        # Method 3: Known model family that supports tools
        for family in cls.KNOWN_TOOL_FAMILIES:
            if family in model_id:
                # Extra check: should be instruct/chat variant, not base model
                if "instruct" in model_id or "chat" in model_id or ":free" in model_id:
                    return True
                # Some families like gpt-4, claude-3 always support tools
                if family in ("gpt-4", "gpt-3.5", "claude-3", "claude-2", "gemini"):
                    return True

        return False

    @classmethod
    async def get_free_models(
        cls,
        api_key: str | None = None,
        limit: int = 20,
        require_tools: bool = True,
    ) -> list[ModelInfo]:
        """Get top free models from OpenRouter.

        Args:
            api_key: Optional API key.
            limit: Maximum models to return.
            require_tools: Only return models that support function calling.

        Returns:
            List of free models sorted by quality.
        """
        all_models = await cls.fetch_openrouter_models(api_key)
        free_models = [m for m in all_models if m.is_free]
        if require_tools:
            free_models = [m for m in free_models if m.supports_tools]
        return free_models[:limit]

    # Fallback Gemini models if API fetch fails
    DEFAULT_GEMINI_MODELS = [
        ModelInfo(
            id="gemini-2.5-flash",
            name="Gemini 2.5 Flash",
            provider=Provider.GEMINI,
            context_length=1_000_000,
            is_free=True,
            rank_score=2.5,
        ),
        ModelInfo(
            id="gemini-2.0-flash",
            name="Gemini 2.0 Flash",
            provider=Provider.GEMINI,
            context_length=1_000_000,
            is_free=True,
            rank_score=1.9,
        ),
    ]

    @classmethod
    async def fetch_gemini_models(cls, api_key: str) -> list[ModelInfo]:
        """Fetch available Gemini models from API.

        Args:
            api_key: Gemini API key.

        Returns:
            List of Gemini models that support generateContent.
        """
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}",
                    timeout=30.0,
                )
                response.raise_for_status()
                data = response.json()

            models: list[ModelInfo] = []
            for m in data.get("models", []):
                # Only include models that support generateContent
                methods = m.get("supportedGenerationMethods", [])
                if "generateContent" not in methods:
                    continue

                model_name = m.get("name", "").replace("models/", "")
                display_name = m.get("displayName", model_name)
                input_limit = m.get("inputTokenLimit", 32000)
                model_lower = model_name.lower()

                # Skip non-chat models
                if "embedding" in model_lower:
                    continue
                if "aqa" in model_lower:
                    continue
                if "tts" in model_lower:  # Text-to-speech
                    continue
                if "imagen" in model_lower:  # Image generation
                    continue
                if "image-generation" in model_lower:
                    continue
                if "audio" in model_lower and "native" not in model_lower:
                    continue
                # Skip Gemma models - they don't support function calling
                if model_lower.startswith("gemma"):
                    continue

                # Calculate rank score based on model version
                rank_score = 1.0
                if "2.5" in model_name:
                    rank_score = 2.5
                elif "2.0" in model_name:
                    rank_score = 2.0
                elif "1.5" in model_name:
                    rank_score = 1.5
                if "pro" in model_name.lower():
                    rank_score += 0.5
                if "flash" in model_name.lower():
                    rank_score += 0.2

                models.append(
                    ModelInfo(
                        id=model_name,
                        name=display_name,
                        provider=Provider.GEMINI,
                        context_length=input_limit,
                        is_free=True,  # Gemini has free tier
                        rank_score=rank_score,
                        supports_tools=True,  # All generateContent models support tools
                    )
                )

            models.sort(key=lambda x: x.rank_score, reverse=True)
            log.info("gemini_models_fetched", total=len(models))
            return models

        except Exception as e:
            log.warning("gemini_fetch_failed", error=str(e))
            return cls.DEFAULT_GEMINI_MODELS

    @classmethod
    def get_gemini_models(cls) -> list[ModelInfo]:
        """Get fallback Gemini models (use fetch_gemini_models for live data).

        Returns:
            List of default Gemini models.
        """
        return cls.DEFAULT_GEMINI_MODELS

    # Fallback Groq models if API fetch fails
    DEFAULT_GROQ_MODELS = [
        ModelInfo(
            id="llama-3.3-70b-versatile",
            name="Llama 3.3 70B Versatile",
            provider=Provider.GROQ,
            context_length=131_072,
            is_free=True,
            rank_score=3.0,
            supports_tools=True,
        ),
        ModelInfo(
            id="llama-3.1-8b-instant",
            name="Llama 3.1 8B Instant",
            provider=Provider.GROQ,
            context_length=131_072,
            is_free=True,
            rank_score=1.5,
            supports_tools=True,
        ),
    ]

    @classmethod
    async def fetch_groq_models(cls, api_key: str) -> list[ModelInfo]:
        """Fetch available Groq models from API.

        Args:
            api_key: Groq API key.

        Returns:
            List of Groq models (excludes whisper/speech models).
        """
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    "https://api.groq.com/openai/v1/models",
                    headers={"Authorization": f"Bearer {api_key}"},
                    timeout=30.0,
                )
                response.raise_for_status()
                data = response.json()

            models: list[ModelInfo] = []
            for m in data.get("data", []):
                model_id = m.get("id", "")
                model_lower = model_id.lower()

                # Skip non-chat models
                if "whisper" in model_lower:  # Speech-to-text
                    continue
                if "tts" in model_lower:  # Text-to-speech
                    continue
                if "playai" in model_lower:  # Audio models
                    continue
                if "guard" in model_lower:  # Safety models
                    continue
                if "distil" in model_lower and "whisper" in model_lower:
                    continue
                # Skip models without tool support
                # Groq compound models don't support tools
                if "compound" in model_lower:
                    continue
                # Arabic language model without tool support
                if "allam" in model_lower:
                    continue

                # Get context length from API or default
                context_length = m.get("context_window", 131_072)

                # Calculate rank score based on model size/type
                rank_score = 1.0
                if "70b" in model_id.lower():
                    rank_score = 3.0
                elif "32b" in model_id.lower():
                    rank_score = 2.5
                elif "8b" in model_id.lower():
                    rank_score = 1.5
                if "versatile" in model_id.lower():
                    rank_score += 0.5

                # Create display name from ID
                display_name = model_id.replace("-", " ").title()

                # Assume all support tools, test will verify
                models.append(
                    ModelInfo(
                        id=model_id,
                        name=display_name,
                        provider=Provider.GROQ,
                        context_length=context_length,
                        is_free=True,  # Groq has free tier
                        rank_score=rank_score,
                        supports_tools=True,
                    )
                )

            models.sort(key=lambda x: x.rank_score, reverse=True)
            log.info("groq_models_fetched", total=len(models))
            return models

        except Exception as e:
            log.warning("groq_fetch_failed", error=str(e))
            return cls.DEFAULT_GROQ_MODELS

    @classmethod
    def get_groq_models(cls) -> list[ModelInfo]:
        """Get fallback Groq models (use fetch_groq_models for live data).

        Returns:
            List of default Groq models.
        """
        return cls.DEFAULT_GROQ_MODELS

    # Fallback Cerebras models if API fetch fails
    DEFAULT_CEREBRAS_MODELS = [
        ModelInfo(
            id="llama-3.3-70b",
            name="Llama 3.3 70B",
            provider=Provider.CEREBRAS,
            context_length=131_072,
            is_free=True,
            rank_score=3.5,
            supports_tools=True,
        ),
        ModelInfo(
            id="llama3.1-8b",
            name="Llama 3.1 8B",
            provider=Provider.CEREBRAS,
            context_length=131_072,
            is_free=True,
            rank_score=1.5,
            supports_tools=True,
        ),
    ]

    @classmethod
    async def fetch_cerebras_models(cls, api_key: str) -> list[ModelInfo]:
        """Fetch available Cerebras models from API.

        Args:
            api_key: Cerebras API key.

        Returns:
            List of Cerebras models.
        """
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    "https://api.cerebras.ai/v1/models",
                    headers={"Authorization": f"Bearer {api_key}"},
                    timeout=30.0,
                )
                response.raise_for_status()
                data = response.json()

            models: list[ModelInfo] = []
            for m in data.get("data", []):
                model_id = m.get("id", "")
                model_lower = model_id.lower()

                # Skip non-chat models
                if "whisper" in model_lower:
                    continue
                if "tts" in model_lower:
                    continue
                if "embedding" in model_lower:
                    continue

                # Calculate rank score based on model size
                rank_score = 1.0
                if "70b" in model_id.lower():
                    rank_score = 3.5
                elif "235b" in model_id.lower() or "120b" in model_id.lower():
                    rank_score = 4.0
                elif "32b" in model_id.lower():
                    rank_score = 2.5
                elif "8b" in model_id.lower():
                    rank_score = 1.5

                # Create display name from ID
                display_name = model_id.replace("-", " ").replace(".", " ").title()

                models.append(
                    ModelInfo(
                        id=model_id,
                        name=display_name,
                        provider=Provider.CEREBRAS,
                        context_length=131_072,  # Most Cerebras models have 128K
                        is_free=True,  # Cerebras has free tier
                        rank_score=rank_score,
                        supports_tools=True,  # Cerebras supports tools
                    )
                )

            models.sort(key=lambda x: x.rank_score, reverse=True)
            log.info("cerebras_models_fetched", total=len(models))
            return models

        except Exception as e:
            log.warning("cerebras_fetch_failed", error=str(e))
            return cls.DEFAULT_CEREBRAS_MODELS

    @classmethod
    def get_cerebras_models(cls) -> list[ModelInfo]:
        """Get fallback Cerebras models (use fetch_cerebras_models for live data).

        Returns:
            List of default Cerebras models.
        """
        return cls.DEFAULT_CEREBRAS_MODELS

    @classmethod
    async def get_all_available_models(
        cls,
        openrouter_key: str | None = None,
        gemini_key: str | None = None,
        groq_key: str | None = None,
        cerebras_key: str | None = None,
        free_only: bool = True,
        require_tools: bool = True,
    ) -> list[ModelInfo]:
        """Get all available models across providers.

        Args:
            openrouter_key: OpenRouter API key.
            gemini_key: Gemini API key.
            groq_key: Groq API key.
            cerebras_key: Cerebras API key.
            free_only: Only return free models.
            require_tools: Only return models that support function calling.

        Returns:
            Combined list of models sorted by rank.
        """
        models: list[ModelInfo] = []

        if openrouter_key:
            or_models = await cls.fetch_openrouter_models(openrouter_key)
            if free_only:
                or_models = [m for m in or_models if m.is_free]
            if require_tools:
                or_models = [m for m in or_models if m.supports_tools]
            models.extend(or_models)

        if gemini_key:
            # Fetch fresh from API
            g_models = await cls.fetch_gemini_models(gemini_key)
            if free_only:
                g_models = [m for m in g_models if m.is_free]
            # Gemini models all support tools
            models.extend(g_models)

        if groq_key:
            # Fetch fresh from API
            groq_models = await cls.fetch_groq_models(groq_key)
            if free_only:
                groq_models = [m for m in groq_models if m.is_free]
            # Groq models all support tools
            models.extend(groq_models)

        if cerebras_key:
            # Fetch fresh from API
            cerebras_models = await cls.fetch_cerebras_models(cerebras_key)
            if free_only:
                cerebras_models = [m for m in cerebras_models if m.is_free]
            # Cerebras models all support tools
            models.extend(cerebras_models)

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
    def find_model_in_groq(cls, model_id: str) -> ModelInfo | None:
        """Find a model by ID in Groq models.

        Args:
            model_id: The model ID to find.

        Returns:
            ModelInfo or None.
        """
        for m in cls.get_groq_models():
            if m.id == model_id:
                return m
        return None

    @classmethod
    async def find_model(
        cls, model_id: str, openrouter_key: str | None = None
    ) -> ModelInfo | None:
        """Find a model by ID (checks static lists first, then fetches OpenRouter).

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

        # Check Groq models (static, fast)
        groq_model = cls.find_model_in_groq(model_id)
        if groq_model:
            return groq_model

        # Check OpenRouter if key provided
        if openrouter_key:
            models = await cls.fetch_openrouter_models(openrouter_key)
            for m in models:
                if m.id == model_id:
                    return m

        return None

    @classmethod
    def apply_test_results(
        cls,
        models: list[ModelInfo],
        test_results: dict[str, bool],
    ) -> list[ModelInfo]:
        """Apply empirical tool test results to models.

        Overlays test results onto the heuristic-based supports_tools field.
        Empirical results take precedence over heuristics.

        Args:
            models: List of models to update.
            test_results: Dict mapping model_id -> supports_tools (from tool_tester).

        Returns:
            Updated list of models with supports_tools reflecting test results.
        """
        updated_models = []
        for model in models:
            if model.id in test_results:
                # Create a new ModelInfo with updated supports_tools
                updated = ModelInfo(
                    id=model.id,
                    name=model.name,
                    provider=model.provider,
                    context_length=model.context_length,
                    is_free=model.is_free,
                    rank_score=model.rank_score,
                    supports_tools=test_results[model.id],
                )
                updated_models.append(updated)
            else:
                updated_models.append(model)
        return updated_models
