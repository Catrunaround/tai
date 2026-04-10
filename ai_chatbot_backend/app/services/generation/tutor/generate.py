from typing import Any, List, Optional

from app.core.models.chat_completion import Message
from app.services.generation.model_call import (
    SAMPLING_PARAMS,
    is_openai_client,
    call_remote_engine,
)
from app.services.generation.schemas import (
    RESPONSE_BLOCKS_JSON_SCHEMA,
    VOICE_TUTOR_OPENAI_FORMAT,
    VOICE_TUTOR_RESPONSE_SCHEMA,
    OUTLINE_OPENAI_FORMAT,
    OUTLINE_JSON_SCHEMA,
)


def _select_json_schema(outline_mode: bool, audio_response: bool):
    """Select the raw JSON schema for guided decoding based on mode flags."""
    if outline_mode:
        return OUTLINE_JSON_SCHEMA
    elif audio_response:
        return VOICE_TUTOR_RESPONSE_SCHEMA
    else:
        return RESPONSE_BLOCKS_JSON_SCHEMA


async def _generate_tutor_local(messages: List[Message], engine: Any, json_schema: dict):
    """
    Call local vLLM for tutor with guided JSON decoding.

    Uses extra_body={"json": schema} for structured output — same pattern
    as generate_bullets.py. Keeps thinking enabled; the base handler
    separates reasoning_content from content automatically.
    """
    from app.config import settings

    chat = [{"role": m.role, "content": m.content} for m in messages]

    stream = await engine.chat.completions.create(
        model=settings.vllm_chat_model,
        messages=chat,
        stream=True,
        temperature=SAMPLING_PARAMS["temperature"],
        top_p=SAMPLING_PARAMS["top_p"],
        max_tokens=SAMPLING_PARAMS["max_tokens"],
        extra_body={
            **SAMPLING_PARAMS["extra_body"],
            "json": json_schema,
        },
    )

    async for chunk in stream:
        if chunk.choices:
            yield chunk


# TODO： add a new function to separate the voice explanation and text explanation.
async def call_tutor_model(
    messages: List[Message],
    engine: Any,
    stream: bool = True,
    audio_response: bool = False,
    course: Optional[str] = None,
    outline_mode: bool = False,
):
    """
    Step 2: Call LLM for tutor mode (with JSON schema).

    Selects the appropriate JSON schema:
    - Outline mode: OUTLINE_OPENAI_FORMAT
    - Voice tutor: VOICE_TUTOR_OPENAI_FORMAT
    - Text tutor: RESPONSE_BLOCKS_OPENAI_FORMAT

    Returns either a streaming iterator or a complete response string.
    """
    if is_openai_client(engine):
        # Local vLLM path — use guided JSON decoding
        json_schema = _select_json_schema(outline_mode, audio_response)
        return _generate_tutor_local(messages, engine, json_schema)


    print("\n" + "=" * 60)
    print("[DEBUG] Full prompt sent to tutor model:")
    print("=" * 60)
    for msg in messages:
        role = msg.role if hasattr(msg, 'role') else 'unknown'
        content = msg.content if hasattr(msg, 'content') else str(msg)
        print(f"\n--- [{role}] ({len(content)} chars) ---")
        print(content)
    print("=" * 60 + "\n")

    if outline_mode:
        response_format = OUTLINE_OPENAI_FORMAT
    elif audio_response:
        response_format = VOICE_TUTOR_OPENAI_FORMAT


    return await call_remote_engine(
        messages, engine, stream=stream, course=course, response_format=response_format
    )
