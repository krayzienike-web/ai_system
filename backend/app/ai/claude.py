"""The real model: Claude through the official SDK (ADR 0005). The only module that imports `anthropic`
(import-linter contract in pyproject.toml).

- Prompt caching: the tools and the system prompt come first and do not change between calls; the cache mark
  sits on the system prompt, so the conversation after it is the only part paid in full.
- Adaptive thinking with an explicit effort; on a refusal the API re-runs the request on a fallback model
  (`fallbacks: "default"`); a refusal that remains comes back as `stop_reason="refusal"`.
- One retry of 408/409/429/5xx and connection errors (the SDK's `max_retries`): a slow answer is not
  paid three times.
"""

from typing import Any

import anthropic

from app.ai.gateway import ModelRequest, ModelUnavailableError, Reply, Usage
from app.core.config import get_settings

FALLBACK_BETA = "server-side-fallback-2026-07-01"


class ClaudeModel:
    def __init__(self, client: anthropic.Anthropic | None = None) -> None:
        settings = get_settings()
        self.effort = settings.ai_effort
        self.client = client or anthropic.Anthropic(timeout=settings.ai_timeout_s, max_retries=1)

    def params(self, request: ModelRequest) -> dict[str, Any]:
        params: dict[str, Any] = {
            "model": request.model,
            "max_tokens": request.max_tokens,
            "system": [{"type": "text", "text": request.system, "cache_control": {"type": "ephemeral"}}],
            "messages": list(request.messages),
            "thinking": {"type": "adaptive"},
            "output_config": {"effort": self.effort},
        }
        if request.tools:
            params["tools"] = list(request.tools)
        if request.model != "claude-haiku-5-5":  # no server-side fallback for Haiku
            params["betas"] = [FALLBACK_BETA]
            params["fallbacks"] = "default"
        return params

    def complete(self, request: ModelRequest) -> Reply:
        try:
            message = self.client.beta.messages.create(**self.params(request))
        except anthropic.APIStatusError as exc:
            raise ModelUnavailableError(f"Claude API {exc.status_code}") from exc
        except anthropic.APIConnectionError as exc:
            raise ModelUnavailableError("Claude API unreachable") from exc
        u = message.usage
        return Reply(
            content=[b.model_dump(mode="json", exclude_none=True) for b in message.content],
            stop_reason=message.stop_reason,
            usage=Usage(
                input_tokens=u.input_tokens,
                output_tokens=u.output_tokens,
                cache_read_tokens=u.cache_read_input_tokens or 0,
                cache_write_tokens=u.cache_creation_input_tokens or 0,
            ),
            model=message.model,
        )
