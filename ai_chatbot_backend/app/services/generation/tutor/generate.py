from typing import Any, List, Optional

from app.core.models.chat_completion import Message
from app.services.generation.model_call import (
    is_openai_client,
    generate_streaming_response,
    call_remote_engine,
)
from app.services.generation.schemas import (
    RESPONSE_BLOCKS_OPENAI_FORMAT,
    VOICE_TUTOR_OPENAI_FORMAT,
)


async def call_tutor_model(
    messages: List[Message],
    engine: Any,
    stream: bool = True,
    audio_response: bool = False,
    course: Optional[str] = None,
):
    """
    Step 2: Call LLM for tutor mode (with JSON schema).

    Selects the appropriate JSON schema based on voice mode:
    - Voice tutor: VOICE_TUTOR_OPENAI_FORMAT
    - Text tutor: RESPONSE_BLOCKS_OPENAI_FORMAT

    Returns either a streaming iterator or a complete response string.
    """
    if is_openai_client(engine):
        return generate_streaming_response(messages, engine)

    # Remote engine: select JSON schema based on voice mode
    response_format = VOICE_TUTOR_OPENAI_FORMAT if audio_response else RESPONSE_BLOCKS_OPENAI_FORMAT

    return await call_remote_engine(
        messages, engine, stream=stream, course=course, response_format=response_format
    )
