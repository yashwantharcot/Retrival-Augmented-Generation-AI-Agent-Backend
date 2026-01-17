import pytest

# This file performs manual OpenAI-based PDF synopsis and is not suitable for automated test runs.
# Skip at module level to avoid external API calls and environment-specific dependencies.
pytest.skip("Skipping manual PDF LLM test; requires API keys and local files.", allow_module_level=True)
