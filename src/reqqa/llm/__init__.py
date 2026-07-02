"""Local LLM access via agent_server (see local-llm-agent-server memory)."""

from reqqa.llm.client import AgentServerClient, LLMError

__all__ = ["AgentServerClient", "LLMError"]
