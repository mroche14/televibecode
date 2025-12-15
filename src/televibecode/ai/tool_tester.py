"""Tool call tester - empirically test which models support function calling."""

import asyncio
import json
import random
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import structlog

from televibecode.ai.models import ModelInfo, ModelRegistry, Provider

log = structlog.get_logger()

# Test results file location
DEFAULT_RESULTS_PATH = Path.home() / ".televibe" / "tool_test_results.json"


@dataclass
class ToolTestResult:
    """Result of testing a model's tool calling capability."""

    model_id: str
    provider: str
    supports_tools: bool
    tested_at: str  # ISO format
    latency_ms: int | None = None
    error: str | None = None


@dataclass
class TestResults:
    """Container for all test results."""

    results: dict[str, ToolTestResult]
    last_full_test: str | None = None  # ISO format of last complete test run

    def to_dict(self) -> dict:
        """Convert to JSON-serializable dict."""
        return {
            "last_full_test": self.last_full_test,
            "results": {k: asdict(v) for k, v in self.results.items()},
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TestResults":
        """Load from dict."""
        results = {}
        for model_id, result_data in data.get("results", {}).items():
            results[model_id] = ToolTestResult(**result_data)
        return cls(
            results=results,
            last_full_test=data.get("last_full_test"),
        )


def load_results(path: Path = DEFAULT_RESULTS_PATH) -> TestResults:
    """Load test results from JSON file."""
    if not path.exists():
        return TestResults(results={})
    try:
        with open(path) as f:
            data = json.load(f)
        return TestResults.from_dict(data)
    except Exception as e:
        log.warning("tool_test_load_failed", error=str(e))
        return TestResults(results={})


def save_results(results: TestResults, path: Path = DEFAULT_RESULTS_PATH) -> None:
    """Save test results to JSON file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(results.to_dict(), f, indent=2)
    log.info("tool_test_results_saved", path=str(path), count=len(results.results))


def needs_testing(results: TestResults) -> bool:
    """Check if we need to run tests today."""
    if not results.last_full_test:
        return True

    try:
        last_test = datetime.fromisoformat(results.last_full_test)
        now = datetime.now(timezone.utc)
        # Test if last test was not today (UTC)
        return last_test.date() < now.date()
    except Exception:
        return True


async def test_single_model(
    model_id: str,
    provider: Provider,
    api_key: str,
) -> ToolTestResult:
    """Test a single model's tool calling capability.

    Uses agno Agent with a simple add_numbers tool.
    """
    from agno.agent import Agent
    from agno.models.groq import Groq
    from agno.models.openrouter import OpenRouter
    from agno.tools import tool

    start_time = datetime.now(timezone.utc)
    tested_at = start_time.isoformat()

    # Generate random numbers so model can't guess the answer
    num_a = random.randint(100, 999)
    num_b = random.randint(100, 999)
    expected_result = num_a + num_b

    # Define a simple test tool - must be inside function to capture random nums
    tool_actually_called = False

    @tool
    def add_numbers(a: int, b: int) -> int:
        """Add two numbers together and return the result."""
        nonlocal tool_actually_called
        tool_actually_called = True
        return a + b

    try:
        # Create model based on provider
        if provider == Provider.OPENROUTER:
            model = OpenRouter(id=model_id, api_key=api_key)
        elif provider == Provider.GEMINI:
            from agno.models.google import Gemini
            model = Gemini(id=model_id, api_key=api_key)
        elif provider == Provider.GROQ:
            model = Groq(id=model_id, api_key=api_key)
        elif provider == Provider.CEREBRAS:
            from agno.models.cerebras import Cerebras
            model = Cerebras(id=model_id, api_key=api_key)
        else:
            return ToolTestResult(
                model_id=model_id,
                provider=provider.value,
                supports_tools=False,
                tested_at=tested_at,
                error=f"Unsupported provider: {provider}",
            )

        # Create agent with test tool
        agent = Agent(
            model=model,
            tools=[add_numbers],
            instructions=(
                "You are a helpful assistant. When asked to add numbers, "
                "you MUST use the add_numbers tool."
            ),
        )

        # Run test with timeout
        async def run_test() -> bool:
            nonlocal tool_actually_called
            prompt = (
                f"Use the add_numbers tool to calculate {num_a} + {num_b}. "
                "You must call the tool."
            )
            response = await asyncio.to_thread(agent.run, prompt)

            # Primary check: tool was actually executed (most reliable)
            if tool_actually_called:
                return True

            # Fallback: check response messages for tool call evidence
            if hasattr(response, 'messages') and response.messages:
                for msg in response.messages:
                    # Check for tool_calls in message
                    if hasattr(msg, 'tool_calls') and msg.tool_calls:
                        return True
                    # Check message role
                    if hasattr(msg, 'role') and msg.role in ('tool', 'function'):
                        return True

            # Last resort: correct answer with random numbers (unlikely to guess)
            if hasattr(response, 'content'):
                response_text = response.content
            else:
                response_text = str(response)
            return str(expected_result) in response_text

        supports_tools = await asyncio.wait_for(run_test(), timeout=30.0)

        elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()
        latency_ms = int(elapsed * 1000)

        return ToolTestResult(
            model_id=model_id,
            provider=provider.value,
            supports_tools=supports_tools,
            tested_at=tested_at,
            latency_ms=latency_ms,
        )

    except TimeoutError:
        return ToolTestResult(
            model_id=model_id,
            provider=provider.value,
            supports_tools=False,
            tested_at=tested_at,
            error="timeout",
        )
    except Exception as e:
        error_msg = str(e)[:200]
        return ToolTestResult(
            model_id=model_id,
            provider=provider.value,
            supports_tools=False,  # If error, assume no support
            tested_at=tested_at,
            error=error_msg,
        )


async def test_models_batch(
    models: list[ModelInfo],
    api_keys: dict[Provider, str],
    max_concurrent: int = 200,
) -> list[ToolTestResult]:
    """Test models concurrently with semaphore-based rate limiting.

    Args:
        models: List of models to test.
        api_keys: Map of provider to API key.
        max_concurrent: Max concurrent tests per provider.

    Returns:
        List of test results.
    """
    results: list[ToolTestResult] = []
    semaphore = asyncio.Semaphore(max_concurrent)

    async def test_with_semaphore(model: ModelInfo) -> ToolTestResult:
        api_key = api_keys.get(model.provider)
        if not api_key:
            return ToolTestResult(
                model_id=model.id,
                provider=model.provider.value,
                supports_tools=False,
                tested_at=datetime.now(timezone.utc).isoformat(),
                error="no_api_key",
            )

        async with semaphore:
            return await test_single_model(model.id, model.provider, api_key)

    log.info("tool_test_starting_all", total_models=len(models), max_concurrent=max_concurrent)

    # Run ALL tests concurrently (semaphore limits actual concurrency)
    tasks = [test_with_semaphore(model) for model in models]
    batch_results = await asyncio.gather(*tasks, return_exceptions=True)

    for result in batch_results:
        if isinstance(result, Exception):
            log.warning("tool_test_exception", error=str(result))
        else:
            results.append(result)

    supported = sum(1 for r in results if r.supports_tools)
    log.info("tool_test_batch_complete", total=len(results), supported=supported)

    return results


async def run_full_test(
    openrouter_key: str | None = None,
    gemini_key: str | None = None,
    groq_key: str | None = None,
    cerebras_key: str | None = None,
    results_path: Path = DEFAULT_RESULTS_PATH,
    force: bool = False,
    max_concurrent_per_provider: int = 50,
) -> TestResults:
    """Run tool test on untested/failed models only (providers tested in parallel).

    Args:
        openrouter_key: OpenRouter API key.
        gemini_key: Gemini API key.
        groq_key: Groq API key.
        cerebras_key: Cerebras API key.
        results_path: Path to save results.
        force: Force re-test all models (ignores cached successes).
        max_concurrent_per_provider: Max concurrent tests per provider.

    Returns:
        Updated TestResults.
    """
    # Load existing results
    results = load_results(results_path)

    log.info("tool_test_starting")

    # Filter function: skip models already confirmed to support tools
    def needs_test(model: ModelInfo) -> bool:
        if force:
            return True
        cached = results.results.get(model.id)
        if cached is None:
            return True  # Never tested
        if cached.supports_tools:
            return False  # Already confirmed working - skip!
        # Failed before - retry if error wasn't definitive
        if cached.error in ("timeout", "no_api_key"):
            return True  # Transient error, retry
        return False  # Confirmed not working

    # Define provider test tasks
    async def test_openrouter() -> list[ToolTestResult]:
        if not openrouter_key:
            return []
        or_models = await ModelRegistry.fetch_openrouter_models(openrouter_key)
        free_or_models = [m for m in or_models if m.is_free]
        # Filter to only untested models
        to_test = [m for m in free_or_models if needs_test(m)]
        log.info(
            "tool_test_openrouter_models",
            total=len(free_or_models),
            to_test=len(to_test),
            skipped=len(free_or_models) - len(to_test),
        )
        if not to_test:
            return []
        # OpenRouter free tier: 16 requests/min limit - use minimal concurrency
        return await test_models_batch(
            to_test,
            {Provider.OPENROUTER: openrouter_key},
            max_concurrent=2,
        )

    async def test_gemini() -> list[ToolTestResult]:
        if not gemini_key:
            return []
        # Fetch fresh model list from API
        gemini_models = await ModelRegistry.fetch_gemini_models(gemini_key)
        to_test = [m for m in gemini_models if needs_test(m)]
        log.info(
            "tool_test_gemini_models",
            total=len(gemini_models),
            to_test=len(to_test),
            skipped=len(gemini_models) - len(to_test),
        )
        if not to_test:
            return []
        # Gemini free tier has strict rate limits - test one at a time
        return await test_models_batch(
            to_test,
            {Provider.GEMINI: gemini_key},
            max_concurrent=1,
        )

    async def test_groq() -> list[ToolTestResult]:
        if not groq_key:
            return []
        # Fetch fresh model list from API
        groq_models = await ModelRegistry.fetch_groq_models(groq_key)
        to_test = [m for m in groq_models if needs_test(m)]
        log.info(
            "tool_test_groq_models",
            total=len(groq_models),
            to_test=len(to_test),
            skipped=len(groq_models) - len(to_test),
        )
        if not to_test:
            return []
        # Groq has generous limits but keep reasonable
        return await test_models_batch(
            to_test,
            {Provider.GROQ: groq_key},
            max_concurrent=5,
        )

    async def test_cerebras() -> list[ToolTestResult]:
        if not cerebras_key:
            return []
        # Fetch fresh model list from API
        cerebras_models = await ModelRegistry.fetch_cerebras_models(cerebras_key)
        to_test = [m for m in cerebras_models if needs_test(m)]
        log.info(
            "tool_test_cerebras_models",
            total=len(cerebras_models),
            to_test=len(to_test),
            skipped=len(cerebras_models) - len(to_test),
        )
        if not to_test:
            return []
        # Cerebras is fast, but keep reasonable concurrency
        return await test_models_batch(
            to_test,
            {Provider.CEREBRAS: cerebras_key},
            max_concurrent=5,
        )

    # Run ALL providers in parallel
    log.info("tool_test_providers_parallel", providers=["openrouter", "gemini", "groq", "cerebras"])
    all_results = await asyncio.gather(
        test_openrouter(),
        test_gemini(),
        test_groq(),
        test_cerebras(),
        return_exceptions=True,
    )

    # Collect results from all providers
    test_results: list[ToolTestResult] = []
    for provider_results in all_results:
        if isinstance(provider_results, Exception):
            log.warning("tool_test_provider_failed", error=str(provider_results))
        else:
            test_results.extend(provider_results)

    # Update results (even if empty, update timestamp)
    for result in test_results:
        results.results[result.model_id] = result

    results.last_full_test = datetime.now(timezone.utc).isoformat()

    # Save results
    save_results(results, results_path)

    # Summary
    if test_results:
        supported = sum(1 for r in test_results if r.supports_tools)
        log.info(
            "tool_test_complete",
            tested=len(test_results),
            supported=supported,
            unsupported=len(test_results) - supported,
            total_cached=len(results.results),
        )
    else:
        log.info(
            "tool_test_complete",
            tested=0,
            message="All models already tested",
            total_cached=len(results.results),
        )

    return results


def get_model_tool_support(model_id: str, results_path: Path = DEFAULT_RESULTS_PATH) -> bool | None:
    """Get cached tool support status for a model.

    Args:
        model_id: Model ID to check.
        results_path: Path to results file.

    Returns:
        True/False if tested, None if not tested.
    """
    results = load_results(results_path)
    if model_id in results.results:
        return results.results[model_id].supports_tools
    return None


def get_tested_models(results_path: Path = DEFAULT_RESULTS_PATH) -> dict[str, bool]:
    """Get all tested models and their tool support status.

    Returns:
        Dict mapping model_id -> supports_tools.
    """
    results = load_results(results_path)
    return {model_id: r.supports_tools for model_id, r in results.results.items()}
