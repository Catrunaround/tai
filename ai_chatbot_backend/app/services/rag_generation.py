# Standard python libraries
import json
import re
import ast
import time
from typing import Any, Optional, Tuple, List, Union
from dataclasses import dataclass
# Third-party libraries
from transformers import AutoTokenizer
from vllm import SamplingParams
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
# Environment Variables
# TOKENIZER_MODEL_ID = "THUDM/GLM-4-9B-0414"
from app.dependencies.model import LLM_MODEL_ID

# TOKENIZER_MODEL_ID = "kaitchup/GLM-Z1-32B-0414-autoround-gptq-4bit"
# RAG-Pipeline Shared Resources
# Block "thinking" wrappers at generation-time (built-in vLLM sampling param).
# This helps prevent models like Qwen-*Thinking* from spending tokens on `<think>...</think>` output.
NO_THINK_BAD_WORDS = ["<think>", "</think>"]

SAMPLING = SamplingParams(
    temperature=0.6, top_p=0.95, top_k=20, min_p=0, max_tokens=6000,
    bad_words=NO_THINK_BAD_WORDS
)
# Sampling params with structured JSON output (uses GuidedDecodingParams for guaranteed valid JSON)
SAMPLING_STRUCTURED = SamplingParams(
    temperature=0.6, top_p=0.95, top_k=20, min_p=0, max_tokens=6000,
    guided_decoding=GUIDED_RESPONSE_BLOCKS,
    bad_words=NO_THINK_BAD_WORDS
)
# Sampling params for voice tutor mode (JSON with unreadable field)
SAMPLING_VOICE_TUTOR = SamplingParams(
    temperature=0.6, top_p=0.95, top_k=20, min_p=0, max_tokens=6000,
    guided_decoding=GUIDED_VOICE_TUTOR_BLOCKS,
    bad_words=NO_THINK_BAD_WORDS
)
TOKENIZER = AutoTokenizer.from_pretrained(LLM_MODEL_ID)

"""
class UserFocus(BaseModel):
    file_uuid: UUID
    selected_text: str = None
    chunk_index: float = None
"""


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

    query_message = await build_retrieval_query(user_message, previous_memory, engine, TOKENIZER, SAMPLING,
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

    if _is_local_engine(engine):
        # Select sampling params based on mode
        if voice_tutor_mode and use_structured_json:
            # Voice Tutor: JSON with unreadable field
            sampling_params = SAMPLING_VOICE_TUTOR
        elif effective_json_output and use_structured_json:
            # Chat Tutor: standard JSON blocks
            sampling_params = SAMPLING_STRUCTURED
        else:
            # Regular modes or prompt-based JSON: no structured decoding
            sampling_params = SAMPLING
        iterator = _generate_streaming_response(messages, engine, sampling_params=sampling_params)
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
        # Wrap OpenAI streaming response to match vLLM output format
        if stream and _is_openai_engine(engine):
            response = _wrap_openai_stream_as_vllm(response)
        return response, reference_list, timer


def _is_local_engine(engine: Any) -> bool:
    """
    Check if the engine is a local instance by verifying if it has an 'is_running' attribute.
    """
    return hasattr(engine, "is_running") and engine.is_running


def _is_openai_engine(engine: Any) -> bool:
    """
    Check if the engine is an OpenAI client.
    """
    return hasattr(engine, '__class__') and 'OpenAI' in engine.__class__.__name__


@dataclass
class MockVLLMOutput:
    """Mock output structure to match vLLM format for OpenAI responses."""
    text: str


@dataclass
class MockVLLMChunk:
    """Mock chunk structure to match vLLM format for OpenAI responses."""
    outputs: List[MockVLLMOutput]


async def _wrap_openai_stream_as_vllm(openai_stream):
    """
    Wrap OpenAI streaming response to match vLLM output format.

    vLLM yields: output.outputs[0].text (cumulative text)
    OpenAI yields: NDJSON strings with incremental tokens

    This wrapper accumulates tokens and yields vLLM-compatible chunks.
    """
    print("\n[DEBUG Wrapper] Starting to wrap OpenAI stream as VLLM format...")
    accumulated_text = ""
    for line in openai_stream:
        print(f"[DEBUG Wrapper] Received line: {line[:100] if line else 'empty'}...")
        if not line or not line.strip():
            continue
        try:
            data = json.loads(line)
            print(f"[DEBUG Wrapper] Parsed data: {data}")
            if data.get("type") == "token":
                accumulated_text += data.get("data", "")
                yield MockVLLMChunk(outputs=[MockVLLMOutput(text=accumulated_text)])
        except json.JSONDecodeError:
            print(f"[DEBUG Wrapper] JSON decode error for: {line[:50]}")
            continue
    print(f"[DEBUG Wrapper] Final accumulated text length: {len(accumulated_text)}")


def _generate_streaming_response(
        messages: List[Message],
        engine: Any = None,
        sampling_params: SamplingParams = None
) -> Any:
    """
    Generate a streaming response from the model based on the provided messages.

    Args:
        messages: List of chat messages
        engine: The LLM engine to use
        sampling_params: Sampling parameters (uses SAMPLING by default, or SAMPLING_STRUCTURED for structured JSON)
    """
    if sampling_params is None:
        sampling_params = SAMPLING
    chat = [
        {"role": m.role, "content": m.content, "tool_call_id": m.tool_call_id}
        for m in messages
    ]
    prompt = TOKENIZER.apply_chat_template(chat, tokenize=False, add_generation_prompt=True)
    return engine.generate(prompt, sampling_params, request_id=str(time.time_ns()))


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
