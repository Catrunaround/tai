# Standard python libraries
import json
import re
import ast
import time
from typing import Any, Optional, Tuple, List, Union
from dataclasses import dataclass
# Third-party libraries
from openai import OpenAI, AsyncOpenAI
# Local libraries
from app.core.models.chat_completion import Message, UserFocus
from app.services.rag_preprocess import build_retrieval_query, build_augmented_prompt, build_file_augmented_context
from app.services.rag_postprocess import (
    GUIDED_RESPONSE_BLOCKS, RESPONSE_BLOCKS_OPENAI_FORMAT,
    GUIDED_VOICE_TUTOR_BLOCKS, VOICE_TUTOR_OPENAI_FORMAT
)
from app.services.request_timer import RequestTimer
from app.prompts import shared, chat, voice
from app.prompts.base import compose
from app.config import settings
from app.dependencies.model import LLM_MODEL_ID

# Sampling parameters for generation (used with OpenAI API)
SAMPLING_PARAMS = {
    "temperature": 0.6,
    "top_p": 0.95,
    "max_tokens": 6000,
    "extra_body": {"top_k": 20, "min_p": 0}
}



async def generate_chat_response(
        messages: List[Message],
        user_focus: Optional[UserFocus] = None,
        answer_content: Optional[str] = None,
        problem_content: Optional[str] = None,
        stream: bool = True,
        course: Optional[str] = None,
        threshold: float = 0.32,
        top_k: int = 7,
        engine: Any = None,
        audio_response: bool = False,
        sid: Optional[str] = None,
        tutor_mode: bool = True,  # Enable tutor mode (Bloom taxonomy, hints-first)
        json_output: bool = True,  # Kept for backward compatibility, derived from tutor_mode
        use_structured_json: bool = True,  # New option: use response_format schema instead of prompt-based JSON
        timer: Optional[RequestTimer] = None  # Optional timer for tracking latency
) -> Tuple[Any, List[str | Any], Optional[RequestTimer]]:
    """
    Build an augmented message with references and run LLM inference.
    Returns a tuple: (stream, reference_string, timer)

    4-Mode System:
    - Chat Tutor (tutor_mode=True, audio_response=False): JSON output with citations-first
    - Chat Regular (tutor_mode=False, audio_response=False): Plain Markdown
    - Voice Tutor (tutor_mode=True, audio_response=True): JSON with unreadable property
    - Voice Regular (tutor_mode=False, audio_response=True): Plain speakable text

    Args:
        tutor_mode: If True, use tutor behavior (Bloom taxonomy, hints-first, JSON output)
        json_output: Kept for backward compatibility. Derived from tutor_mode if not explicitly set.
        use_structured_json: If True AND using JSON output, use response_format schema
                            for guaranteed valid JSON. If False, use prompt-based JSON instructions.
        timer: Optional RequestTimer for tracking latency milestones
    """
    # Derive json_output from tutor_mode (both tutor modes use JSON)
    # json_output is True for tutor modes, False for regular modes
    effective_json_output = tutor_mode

    # Determine if this is voice tutor mode (special JSON schema with unreadable)
    voice_tutor_mode = tutor_mode and audio_response

    # Build the query message based on the chat history
    t0 = time.time()

    messages = format_chat_msg(
        messages,
        tutor_mode=tutor_mode,
        audio_response=audio_response,
        use_structured_json=use_structured_json
    )

    user_message = messages[-1].content
    messages[-1].content = ""

    filechat_focused_chunk = ""
    filechat_file_sections = []

    file_uuid = None
    selected_text = None
    index = None

    if user_focus:
        file_uuid = user_focus.file_uuid
        selected_text = user_focus.selected_text
        index = user_focus.chunk_index

    if file_uuid:
        augmented_context, file_content, filechat_focused_chunk, filechat_file_sections = build_file_augmented_context(
            file_uuid, selected_text, index)
        messages[-1].content = (
            f"{augmented_context}"
            f"Below are the relevant references for answering the user:\n\n"
        )

    # Graceful memory retrieval from MongoDB
    previous_memory = None
    if sid and len(messages) > 2:
        try:
            from app.services.memory_synopsis_service import MemorySynopsisService
            memory_service = MemorySynopsisService()
            previous_memory = await memory_service.get_by_chat_history_sid(sid)
        except Exception as e:
            print(f"[INFO] Failed to retrieve memory for query building, continuing without: {e}")
            previous_memory = None

    if timer:
        timer.mark("query_reformulation_start")

    query_message = await build_retrieval_query(user_message, previous_memory, engine,
                                                filechat_file_sections, filechat_focused_chunk)

    if timer:
        timer.mark("query_reformulation_end")

    print(f"[INFO] Preprocessing time: {time.time() - t0:.2f} seconds")

    # Build modified prompt with references

    modified_message, reference_list, system_add_message = build_augmented_prompt(
        user_message,
        course if course else "",
        threshold,
        True,
        top_k=top_k,
        problem_content=problem_content,
        answer_content=answer_content,
        query_message=query_message,
        audio_response=audio_response,
        tutor_mode=tutor_mode,
        timer=timer
    )
    # Update the last message with the modified content
    messages[-1].content += modified_message
    messages[0].content += system_add_message
    # Generate the response using the engine
    if timer:
        timer.mark("llm_generation_start")

    if _is_openai_client(engine):
        iterator = _generate_streaming_response(messages, engine)
        return iterator, reference_list, timer
    else:
        # For remote engines (RemoteModelClient, OpenAIModelClient), pass structured JSON format if enabled
        if voice_tutor_mode and use_structured_json:
            response_format = VOICE_TUTOR_OPENAI_FORMAT
        elif effective_json_output and use_structured_json:
            response_format = RESPONSE_BLOCKS_OPENAI_FORMAT
        else:
            response_format = None
        # Remote path: do NOT send chat history; only send system + the final user prompt.
        remote_messages = [
            {"role": messages[0].role, "content": messages[0].content},
            {"role": messages[-1].role, "content": messages[-1].content},
        ]
        response = engine(
            messages[-1].content,
            messages=remote_messages,
            stream=stream,
            course=course,
            response_format=response_format,
        )
        return response, reference_list, timer


def _is_openai_client(engine: Any) -> bool:
    """
    Check if the engine is an OpenAI or AsyncOpenAI client instance.
    """
    return isinstance(engine, (OpenAI, AsyncOpenAI))


@dataclass
class MockVLLMOutput:
    """Mock output structure to match vLLM format for OpenAI responses."""
    text: str


@dataclass
class MockVLLMChunk:
    """Mock chunk structure to match vLLM format for OpenAI responses."""
    outputs: List[MockVLLMOutput]


async def _generate_streaming_response(messages: List[Message], client: Any):
    """
    Generate a streaming response from the vLLM server using OpenAI chat completions API.

    Yields raw streaming chunks that contain:
    - delta.reasoning_content: The reasoning/thinking content (analysis channel)
    - delta.content: The final response content (final channel)

    The vLLM server with --reasoning-parser flag separates these automatically.
    """
    chat = [
        {"role": m.role, "content": m.content}
        for m in messages
    ]

    stream = await client.chat.completions.create(
        model=settings.vllm_chat_model,
        messages=chat,
        stream=True,
        temperature=SAMPLING_PARAMS["temperature"],
        top_p=SAMPLING_PARAMS["top_p"],
        max_tokens=SAMPLING_PARAMS["max_tokens"],
        extra_body=SAMPLING_PARAMS["extra_body"]
    )

    # Yield raw chunks - chat_stream_parser handles reasoning_content vs content
    async for chunk in stream:
        if chunk.choices:
            yield chunk



def format_chat_msg(
    messages: List[Message],
    tutor_mode: bool = True,
    audio_response: bool = False,
    use_structured_json: bool = False
) -> List[Message]:
    """
    Format a conversation by prepending an initial system message based on the 4-mode system.

    4-Mode System:
    - Chat Tutor (tutor_mode=True, audio_response=False): JSON output with tutor guidance
    - Chat Regular (tutor_mode=False, audio_response=False): Plain Markdown, direct answers
    - Voice Tutor (tutor_mode=True, audio_response=True): JSON with unreadable property
    - Voice Regular (tutor_mode=False, audio_response=True): Plain speakable text

    Args:
        messages: List of chat messages
        tutor_mode: If True, use tutor behavior (Bloom taxonomy, hints-first)
        audio_response: If True, output will be converted to speech
        use_structured_json: If True, use simplified prompt (schema enforces structure).
                            If False, use detailed prompt-based JSON instructions.
    """
    response: List[Message] = []

    # Build system message using composable prompts
    # Always start with shared identity and language matching
    fragments = [
        shared.TAI_IDENTITY,
        shared.LANGUAGE_MATCHING,
    ]

    if audio_response:
        if tutor_mode:
            # Voice Tutor Mode: JSON with unreadable property
            fragments.extend([
                shared.TUTOR_GUIDANCE,
                voice.VOICE_TUTOR_FORMAT,
                voice.VOICE_TUTOR_UNREADABLE_RULES,
                shared.OFF_TOPIC_HANDLING,
            ])
        else:
            # Voice Regular Mode: plain speakable text
            fragments.extend([
                shared.REGULAR_MODE_GUIDANCE,
                voice.VOICE_REGULAR_STYLE,
                shared.OFF_TOPIC_HANDLING,
            ])
    else:
        if tutor_mode:
            # Chat Tutor Mode: JSON with tutor guidance
            fragments.extend([
                shared.TUTOR_GUIDANCE,
                shared.OFF_TOPIC_HANDLING,
            ])
            # Add JSON format prompts (structured or prompt-based)
            format_prompts = chat.get_format_prompts(use_structured_json)
            fragments.extend(format_prompts)
            fragments.append(chat.TUTOR_JSON_CITATION_RULES)
        else:
            # Chat Regular Mode: plain markdown
            fragments.extend([
                shared.REGULAR_MODE_GUIDANCE,
                chat.REGULAR_MARKDOWN_STYLE,
                shared.OFF_TOPIC_HANDLING,
            ])

    system_message = compose(*fragments, separator="\n")

    response.append(Message(role="system", content=system_message))
    for message in messages:
        response.append(Message(role=message.role, content=message.content))
    return response


#############################################################################
########################### UNKNOWN USAGE YET ###############################
#############################################################################


def _to_str_list(x: Union[str, List], *, trim=True) -> List[str]:
    if isinstance(x, list):
        items = x
    elif isinstance(x, str):
        try:
            parsed = json.loads(x)
            items = parsed if isinstance(parsed, list) else [str(parsed)]
        except Exception:
            try:
                parsed = ast.literal_eval(x)
                items = parsed if isinstance(parsed, list) else [str(parsed)]
            except Exception:
                parts = re.findall(r'"([^"]+)"|\'([^\']+)\'', x)
                items = [a or b for a, b in parts]
    else:
        items = [str(x)]

    items = ["" if i is None else str(i) for i in items]
    if trim:
        items = [i.strip() for i in items]
    return [i for i in items if i != ""]


def join_titles(info_path: Union[str, List], *, sep=" > ", start=0) -> str:
    items = _to_str_list(info_path)
    items = items[start:]
    return sep.join(items)
