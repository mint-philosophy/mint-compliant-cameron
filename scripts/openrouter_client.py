"""
OpenRouter API client for v4 generation pipeline.
Uses OpenAI SDK with OpenRouter base URL.
"""
from __future__ import annotations

import os
import logging
import time
from dataclasses import dataclass, field

import openai
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "google/gemini-3-pro-preview"


@dataclass
class GenerationResult:
    """Result from an API call, including content and token usage."""
    content: str | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    reasoning_tokens: int = 0
    cached_tokens: int = 0
    model: str = ""

    @property
    def visible_tokens(self) -> int:
        return self.completion_tokens - self.reasoning_tokens

    def usage_dict(self) -> dict:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "reasoning_tokens": self.reasoning_tokens,
            "cached_tokens": self.cached_tokens,
            "visible_tokens": self.visible_tokens,
        }


class OpenRouterClient:
    """Wrapper for OpenRouter API using the OpenAI SDK."""

    def __init__(self, model_name: str | None = None, api_key: str | None = None):
        self.api_key = api_key or os.getenv("OPENROUTER_API_KEY")
        if not self.api_key:
            raise ValueError("OPENROUTER_API_KEY environment variable is not set.")

        self.model_name = model_name or DEFAULT_MODEL

        self.client = openai.OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=self.api_key,
        )
        logger.info(f"OpenRouterClient initialized with model: {self.model_name}")

    def generate(
        self,
        prompt: str,
        system_prompt: str = "You are a helpful assistant.",
        temperature: float = 0.7,
        max_tokens: int = 4000,
        json_mode: bool = False,
        extra_body: dict | None = None,
    ) -> GenerationResult:
        """Single-turn completion. Returns GenerationResult with content and usage."""
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ]

        kwargs: dict = {
            "model": self.model_name,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        if extra_body:
            # If extra_body sets max_completion_tokens (for reasoning models),
            # drop the default max_tokens to avoid conflicts
            if "max_completion_tokens" in extra_body:
                del kwargs["max_tokens"]
            kwargs["extra_body"] = extra_body

        try:
            response = self.client.chat.completions.create(**kwargs)

            result = GenerationResult(
                content=response.choices[0].message.content,
                model=getattr(response, "model", self.model_name),
            )

            # Extract token usage
            usage = response.usage
            if usage:
                result.prompt_tokens = usage.prompt_tokens or 0
                result.completion_tokens = usage.completion_tokens or 0
                if hasattr(usage, "completion_tokens_details") and usage.completion_tokens_details:
                    result.reasoning_tokens = getattr(
                        usage.completion_tokens_details, "reasoning_tokens", 0
                    ) or 0
                if hasattr(usage, "prompt_tokens_details") and usage.prompt_tokens_details:
                    result.cached_tokens = getattr(
                        usage.prompt_tokens_details, "cached_tokens", 0
                    ) or 0

            return result

        except Exception as e:
            logger.error(f"Error generating completion: {e}")
            raise

    def generate_with_retry(
        self,
        prompt: str,
        system_prompt: str = "You are a helpful assistant.",
        temperature: float = 0.7,
        max_tokens: int = 4000,
        json_mode: bool = False,
        retries: int = 5,
        base_delay: float = 2.0,
        extra_body: dict | None = None,
    ) -> GenerationResult | None:
        """Generate with exponential backoff retry. Returns GenerationResult or None."""
        last_error = None
        for attempt in range(retries):
            try:
                result = self.generate(
                    prompt=prompt,
                    system_prompt=system_prompt,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    json_mode=json_mode,
                    extra_body=extra_body,
                )
                if result.content:
                    return result
                logger.warning(f"Attempt {attempt + 1}: empty response")
            except Exception as e:
                last_error = e
                logger.warning(f"Attempt {attempt + 1}/{retries} failed: {e}")

            wait = base_delay * (2 ** attempt)
            logger.info(f"Waiting {wait:.1f}s before retry...")
            time.sleep(wait)

        logger.error(f"All {retries} attempts failed. Last error: {last_error}")
        return None
