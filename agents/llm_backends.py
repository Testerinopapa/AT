"""LLM backend helpers for the agents package."""
from __future__ import annotations

import os
from typing import Any, Dict, Optional

import requests


class OpenRouterLLMBackend:
    """Simple wrapper around the OpenRouter chat completions endpoint.

    Parameters
    ----------
    api_key:
        API key used for authentication. If omitted, the ``OPENROUTER_API_KEY``
        environment variable is used.
    model:
        Model identifier to request from OpenRouter. Defaults to
        ``"@preset/tradebot"``.
    base_url:
        Endpoint for chat completions.
    timeout:
        Optional timeout (in seconds) for the HTTP request.
    extra_headers:
        Additional headers to include with each request.
    system_prompt:
        Optional system-level message prepended to the user prompt.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        *,
        model: str = "@preset/tradebot",
        base_url: str = "https://openrouter.ai/api/v1/chat/completions",
        timeout: Optional[float] = 30.0,
        extra_headers: Optional[Dict[str, str]] = None,
        system_prompt: Optional[str] = None,
    ) -> None:
        self.api_key = api_key or os.environ.get("OPENROUTER_API_KEY")
        self.model = model
        self.base_url = base_url
        self.timeout = timeout
        self.extra_headers = extra_headers or {}
        self.system_prompt = system_prompt

    def __call__(self, prompt: str) -> Dict[str, Any]:
        return self.run(prompt)

    def run(self, prompt: str) -> Dict[str, Any]:
        if not self.api_key:
            raise RuntimeError(
                "OPENROUTER_API_KEY must be provided either explicitly or via the environment."
            )

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            **self.extra_headers,
        }

        messages = []
        if self.system_prompt:
            messages.append({"role": "system", "content": self.system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self.model,
            "messages": messages,
        }

        response = requests.post(
            self.base_url,
            headers=headers,
            json=payload,
            timeout=self.timeout,
        )
        response.raise_for_status()
        data = response.json()

        content = None
        choices = data.get("choices")
        if isinstance(choices, list) and choices:
            message = choices[0].get("message", {})
            content = message.get("content")

        return {"content": content, "raw": data}
