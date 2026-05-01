from typing import Any, List, Optional

from app.config import settings
from app.core.models.chat_completion import Message
from app.services.generation.model_call import SAMPLING_PARAMS, call_remote_engine
from app.services.generation.schemas import PAGE_CONTENT_OPENAI_FORMAT, PAGE_CONTENT_JSON_SCHEMA


async def call_page_content_model(messages: List[Message], engine: Any):
    """
    Call the local vLLM model for page content generation.

    No response_format — output is plain markdown, not JSON.
    Yields raw streaming chunks from the vLLM server.
    """
    chat = [{"role": m.role, "content": m.content} for m in messages]

    stream = await engine.chat.completions.create(
        model=settings.vllm_chat_model,
        messages=chat,
        stream=True,
        temperature=SAMPLING_PARAMS["temperature"],
        top_p=SAMPLING_PARAMS["top_p"],
        max_tokens=SAMPLING_PARAMS["max_tokens"],
        extra_body=SAMPLING_PARAMS["extra_body"],
    )

    async for chunk in stream:
        if chunk.choices:
            yield chunk


async def call_page_content_openai(
    messages: List[Message],
    engine: Any,
    course: Optional[str] = None,
):
    """
    Call OpenAI for page content generation with block-based JSON schema.

    Returns a streaming iterator of chunks (same interface as call_remote_engine).
    Uses PAGE_CONTENT_OPENAI_FORMAT for structured output with blocks.
    """
    return await call_remote_engine(
        messages,
        engine,
        stream=True,
        course=course,
        response_format=PAGE_CONTENT_OPENAI_FORMAT,
    )


async def call_page_content_html(
    messages: List[Message],
    engine: Any,
    course: Optional[str] = None,
    max_tokens: int = 8192,
):
    """
    Call OpenAI for HTML fragment or interactive HTML generation.

    No response_format — model outputs raw HTML using preset CSS classes.
    Higher max_tokens than default because interactive mode generates
    complete HTML+CSS+JS documents.
    Returns a streaming iterator of chunks.
    """
    return await call_remote_engine(
        messages,
        engine,
        stream=True,
        course=course,
        max_tokens=max_tokens,
    )


async def call_page_content_local(
    messages: List[Message],
    engine: Any,
):
    """
    Call local vLLM for page content generation.

    The model generates slide-style markdown content based on prompt instructions.
    No structured output constraint — the prompt guides the format.
    Returns a streaming iterator of chunks.
    """
    chat = [{"role": m.role, "content": m.content} for m in messages]

    stream = await engine.chat.completions.create(
        model=settings.vllm_chat_model,
        messages=chat,
        stream=True,
        temperature=SAMPLING_PARAMS["temperature"],
        top_p=SAMPLING_PARAMS["top_p"],
        max_tokens=SAMPLING_PARAMS["max_tokens"],
        extra_body={
            "top_k": SAMPLING_PARAMS["extra_body"]["top_k"],
            "min_p": SAMPLING_PARAMS["extra_body"]["min_p"],
            "chat_template_kwargs": {"enable_thinking": False},
        },
    )

    return stream
