"""
OpenRouter API client for v4 generation pipeline.
Uses OpenAI SDK with OpenRouter base URL for Gemini Pro access.
"""
from __future__ import annotations

import os
import logging
import time

import openai
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "google/gemini-3-pro-preview"


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
    ) -> str | None:
        """Single-turn completion with optional JSON mode and provider-specific params."""
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
            kwargs["extra_body"] = extra_body

        try:
            response = self.client.chat.completions.create(**kwargs)
            return response.choices[0].message.content
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
    ) -> str | None:
        """Generate with exponential backoff retry."""
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
                if result:
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
