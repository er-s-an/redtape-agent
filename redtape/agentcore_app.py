# pyright: reportMissingImports=false
"""Stretch: deploy the agent to Amazon Bedrock AgentCore Runtime.

    pip install -e ".[agentcore]"
    npm i -g @aws/agentcore
    agentcore create && agentcore deploy

(bedrock_agentcore is the optional [agentcore] extra — not installed for the
local demo, so the import is intentionally unresolved there.)
"""
from __future__ import annotations

from bedrock_agentcore.runtime import BedrockAgentCoreApp

from .agent import build_agent
from .paths import DATA_DIR
from .store import Store
from .tools import init_context
import os
from datetime import date

app = BedrockAgentCoreApp()
_agent = None


def _agent_lazy():
    global _agent
    if _agent is None:
        store = Store(DATA_DIR / "redtape.db")
        init_context(store, os.environ.get("MOCKGOV_BASE", "http://localhost:9100"),
                     date.today(), DATA_DIR)
        _agent = build_agent(DATA_DIR)
    return _agent


@app.entrypoint
def invoke(payload: dict) -> str:
    prompt = payload.get("prompt", "")
    return str(_agent_lazy()(prompt))


if __name__ == "__main__":
    app.run()
