"""
OpenAI API client for structured output generation.

Provides the same interface as RemoteModelClient for seamless integration.
Supports OpenAI's native structured output (response_format with json_schema).
"""
import json
from typing import Optional, Dict, Any, Iterator

from openai import OpenAI


class OpenAIModelClient:
    """
    OpenAI API client that matches RemoteModelClient interface.

    Uses OpenAI's native structured output support for guaranteed valid JSON
    when response_format parameter is provided.
    """

    def __init__(
        self,
        api_key: str,
        model: str = "gpt-4o",
    ):
        """
        Initialize OpenAI client.

        Args:
            api_key: OpenAI API key
            model: Model to use (e.g., gpt-4o, gpt-4o-mini)
        """
        if not api_key:
            raise ValueError("OpenAI API key is required. Set OPENAI_API_KEY in .env")

        self.model = model
        self.client = OpenAI(api_key=api_key)

    def __call__(
        self,
        prompt: str,
        **kwargs
    ) -> Iterator[str] | Dict[str, Any]:
        """
        Send a chat completion request to OpenAI.

        Args:
            prompt: The user prompt (used as fallback if messages not provided)
            **kwargs:
                messages: List of message dicts (preferred over prompt)
                stream: Whether to stream the response
                temperature: Sampling temperature (default: 0.7)
                response_format: OpenAI response_format for structured output
                max_tokens: Maximum tokens to generate

        Returns:
            If streaming: Iterator yielding NDJSON strings (matching RemoteModelClient format)
            If not streaming: Complete response dict
        """
        messages = kwargs.get("messages", [{"role": "user", "content": prompt}])
        stream = kwargs.get("stream", False)
        temperature = kwargs.get("temperature", 0.7)
        response_format = kwargs.get("response_format")
        max_tokens = kwargs.get("max_tokens", 6000)

        # Build request params
        request_params = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": stream,
        }

        # Add response_format for structured output
        if response_format is not None:
            request_params["response_format"] = response_format

        try:
            response = self.client.chat.completions.create(**request_params)

            if stream:
                return self._stream_response(response)
            else:
                return self._format_response(response)

        except Exception as e:
            raise Exception(f"OpenAI API request failed: {str(e)}")

    def _stream_response(self, response) -> Iterator[str]:
        """
        Convert OpenAI streaming response to NDJSON format matching RemoteModelClient.

        Yields NDJSON strings in format: {"type": "token", "data": "..."}
        """
        for chunk in response:
            if chunk.choices and chunk.choices[0].delta.content:
                yield json.dumps({
                    "type": "token",
                    "data": chunk.choices[0].delta.content
                }) + "\n"

    def _format_response(self, response) -> Dict[str, Any]:
        """Format complete response to match expected structure."""
        return {
            "content": response.choices[0].message.content,
            "model": response.model,
            "usage": {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            }
        }
