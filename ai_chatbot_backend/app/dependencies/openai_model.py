"""
OpenAI API client for structured output generation.

Provides the same interface as RemoteModelClient for seamless integration.
Supports OpenAI's native structured output (response_format with json_schema).
"""
import json
from typing import Optional, Dict, Any, Iterator

from openai import AsyncOpenAI


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
        self.client = AsyncOpenAI(api_key=api_key)

    @staticmethod
    def _should_use_responses_api(model: str) -> bool:
        """
        Heuristic: GPT-5.x models prefer the Responses API for proper streaming.
        """
        if not model:
            return False
        model_l = model.lower()
        return model_l.startswith("gpt-5") or model_l.startswith("gpt5")

    @staticmethod
    def _convert_response_format_for_responses(response_format: Dict[str, Any]) -> Dict[str, Any]:
        """
        Convert chat.completions response_format (json_schema wrapper) to
        responses API text.format schema.
        """
        if not isinstance(response_format, dict):
            return response_format
        if response_format.get("type") == "json_schema" and "json_schema" in response_format:
            schema_block = response_format.get("json_schema") or {}
            if isinstance(schema_block, dict):
                converted = {"type": "json_schema"}
                converted.update(schema_block)
                return converted
        return response_format

    async def __call__(
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
        temperature = kwargs.get("temperature")
        response_format = kwargs.get("response_format")
        max_tokens = kwargs.get("max_tokens")

        use_responses_api = self._should_use_responses_api(self.model) and hasattr(self.client, "responses")

        if use_responses_api:
            response_params = {
                "model": self.model,
                "input": messages,
                "stream": stream,
            }
            if temperature is not None:
                response_params["temperature"] = temperature
            if max_tokens is not None:
                response_params["max_output_tokens"] = max_tokens
            if response_format is not None:
                response_params["text"] = {
                    "format": self._convert_response_format_for_responses(response_format)
                }
            try:
                response = await self.client.responses.create(**response_params)
                if stream:
                    return self._stream_response_responses(response)
                return self._format_responses_response(response)
            except Exception as e:
                raise Exception(f"OpenAI Responses API request failed: {str(e)}")

        # Build request params for chat.completions
        request_params = {
            "model": self.model,
            "messages": messages,
            # "temperature": temperature,
            # "max_tokens": max_tokens,
            "stream": stream,
        }

        # Add response_format for structured output
        if response_format is not None:
            request_params["response_format"] = response_format

        try:
            response = await self.client.chat.completions.create(**request_params)

            if stream:
                return self._stream_response(response)
            return self._format_response(response)

        except Exception as e:
            raise Exception(f"OpenAI API request failed: {str(e)}")

    async def _stream_response(self, response) -> Iterator[str]:
        """
        Convert OpenAI streaming response to NDJSON format matching RemoteModelClient.

        Yields NDJSON strings in format: {"type": "token", "data": "..."}
        """
        print("\n[OpenAI Stream] Starting streaming response (chat.completions)...")
        accumulated = ""
        async for chunk in response:
            # Debug: log raw chunk structure
            # print(f"\n[DEBUG OpenAI Chat] Chunk: {chunk}")
            # print(f"[DEBUG OpenAI Chat] choices: {chunk.choices if chunk.choices else 'none'}")
            # if chunk.choices and chunk.choices[0].delta:
            #     print(f"[DEBUG OpenAI Chat] delta: {chunk.choices[0].delta}")
            #     print(f"[DEBUG OpenAI Chat] delta.content: {chunk.choices[0].delta.content}")

            if chunk.choices and chunk.choices[0].delta.content:
                token = chunk.choices[0].delta.content
                accumulated += token
                print(token, end="", flush=True)
                yield json.dumps({
                    "type": "token",
                    "data": token
                }) + "\n"
        print("\n[OpenAI Stream] Complete. Full response:")
        print(accumulated)
        print("[OpenAI Stream] End of response\n")

    async def _stream_response_responses(self, response) -> Iterator[str]:
        """
        Convert OpenAI Responses API streaming events to NDJSON token stream.
        """
        print("\n[OpenAI Stream] Starting streaming response (responses API / GPT-5.x)...")
        accumulated = ""
        async for event in response:
            event_type = getattr(event, "type", "")
            if event_type == "response.output_text.delta":
                token = event.delta
                if token:
                    accumulated += token
                    print(token, end="", flush=True)
                    yield json.dumps({
                        "type": "token",
                        "data": token
                    }) + "\n"
            elif event_type == "response.refusal.delta":
                token = event.delta
                if token:
                    accumulated += token
                    print(token, end="", flush=True)
                    yield json.dumps({
                        "type": "token",
                        "data": token
                    }) + "\n"
        print("\n[OpenAI Stream] Complete. Full response:")
        print(accumulated)
        print("[OpenAI Stream] End of response\n")

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

    def _format_responses_response(self, response) -> Dict[str, Any]:
        """Format complete Responses API response to match expected structure."""
        usage = {}
        if getattr(response, "usage", None):
            usage = {
                "prompt_tokens": response.usage.input_tokens,
                "completion_tokens": response.usage.output_tokens,
                "total_tokens": response.usage.total_tokens,
            }
        return {
            "content": response.output_text,
            "model": response.model,
            "usage": usage,
        }
