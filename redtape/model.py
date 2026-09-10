"""Model wiring. Dev/demo default: Kimi for Coding (K2.7) via its OpenAI-compatible
endpoint. Strands is model-agnostic — set REDTAPE_PROVIDER=bedrock to run on
Amazon Bedrock instead (used for the AgentCore deployment path).
"""
from __future__ import annotations

import os

from strands.models.model import Model


def build_model() -> Model:
    provider = os.environ.get("REDTAPE_PROVIDER", "kimi")
    if provider == "kimi":
        from strands.models.openai import OpenAIModel

        return OpenAIModel(
            client_args={
                "api_key": os.environ["KIMI_CODE_API_KEY"],
                "base_url": "https://api.kimi.com/coding/v1",
            },
            model_id=os.environ.get("REDTAPE_MODEL_ID", "kimi-for-coding"),
            params={"max_tokens": 8192},
        )
    if provider == "bedrock":
        from strands.models.bedrock import BedrockModel

        return BedrockModel(
            model_id=os.environ.get("REDTAPE_MODEL_ID", "us.anthropic.claude-sonnet-4-6"),
        )
    raise ValueError(f"unknown REDTAPE_PROVIDER: {provider}")
