# Standard python libraries
import json
import re
import ast
import time
from typing import Any, Optional, Tuple, List, Union, Generator
# Third-party libraries
from transformers import AutoTokenizer
from vllm import SamplingParams
# Local libraries
from app.core.models.chat_completion import Message, UserFocus
from app.services.rag_preprocess import build_retrieval_query, build_augmented_prompt, build_file_augmented_context
from app.services.sentence_citation_service import (
    SentenceCitationService,
    CITATION_SAMPLING_PARAMS,
    SIMPLE_CITATION_SAMPLING_PARAMS
)
from app.services.citation_enhancement import (
    enhance_citations_with_metadata,
    parse_llm_citation_response
)
# Environment Variables
# TOKENIZER_MODEL_ID = "THUDM/GLM-4-9B-0414"
from app.dependencies.model import LLM_MODEL_ID
# TOKENIZER_MODEL_ID = "kaitchup/GLM-Z1-32B-0414-autoround-gptq-4bit"
# RAG-Pipeline Shared Resources
SAMPLING = SamplingParams(temperature=0.6, top_p=0.95,top_k=20,min_p=0, max_tokens=6000)
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
        enable_sentence_citations: bool = True,
        use_simple_json: bool = False
) -> Tuple[Any, List[str | Any]]:
    """
    Build an augmented message with references and run LLM inference.
    Returns a tuple: (stream, reference_string)

    Args:
        enable_sentence_citations: If True, request structured output with sentence citations
        use_simple_json: If True, use simple JSON format {"answer": "...", "mentioned_contexts": [...]}
    """
    # Build the query message based on the chat history
    t0 = time.time()

    messages = format_chat_msg(
        messages,
        enable_citations=enable_sentence_citations or use_simple_json,
        use_simple_json=use_simple_json
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

    query_message = await build_retrieval_query(user_message, previous_memory, engine, TOKENIZER, SAMPLING,
                                                filechat_file_sections, filechat_focused_chunk)

    print(f"[INFO] Preprocessing time: {time.time() - t0:.2f} seconds")

    # Build modified prompt with references

    modified_message, reference_list, system_add_message = build_augmented_prompt(
        user_message,
        course if course else "",
        threshold,
        True,
        top_k = top_k,
        problem_content = problem_content,
        answer_content = answer_content,
        query_message=query_message,
        audio_response=audio_response
    )
    # Update the last message with the modified content
    messages[-1].content += modified_message
    messages[0].content += system_add_message
    # Generate the response using the engine
    if _is_local_engine(engine):
        # Select sampling params based on citation format
        if use_simple_json:
            # Simple JSON format: {"answer": "...", "mentioned_contexts": [...]}
            sampling_params = SIMPLE_CITATION_SAMPLING_PARAMS
        elif enable_sentence_citations:
            # Complex citation format with sentence-level details
            sampling_params = CITATION_SAMPLING_PARAMS
        else:
            # No guided decoding
            sampling_params = None

        iterator = _generate_streaming_response(messages, engine, sampling_params)
        return iterator, reference_list
    else:
        response = engine(messages[-1].content, stream=stream, course=course)
        return response, reference_list

def enhance_references_v2(
    response_text: str,
    reference_list: List[List]
) -> Tuple[str, List[dict[str, Any]]]:
    """
    Enhanced version using reference numbers from LLM response.

    This is the newer approach that uses reference numbers from the LLM's
    structured JSON output to map citations directly to file_uuid.

    Args:
        response_text: Full LLM response containing JSON with mentioned_contexts
        reference_list: Reference list [[topic_path, url, file_path, file_uuid, chunk_index], ...]

    Returns:
        Tuple of (answer_text, enhanced_reference_list)
        enhanced_reference_list contains dicts with:
            - topic_path, url, file_path, file_uuid, chunk_index
            - sentences: List of dicts with content, page_index, bbox, confidence
    """
    # Parse LLM response to extract answer and mentioned contexts
    answer, mentioned_contexts = parse_llm_citation_response(response_text)

    # If no mentioned contexts, return basic reference format
    if not mentioned_contexts:
        enhanced = []
        return answer, enhanced

    # Enhance citations with file metadata and sentence positions
    enhanced_refs = enhance_citations_with_metadata(
        mentioned_contexts,
        reference_list
    )

    # Convert EnhancedReference objects to dicts
    enhanced_dicts = []
    for ref in enhanced_refs:
        ref_dict = {
            "topic_path": ref.topic_path,
            "url": ref.url,
            "file_path": ref.file_path,
            "file_uuid": ref.file_uuid,
            "chunk_index": ref.chunk_index,
            "sentences": None
        }

        if ref.sentences:
            ref_dict["sentences"] = [
                {
                    "content": s.content,
                    "page_index": s.page_index,
                    "bbox": s.bbox,
                    "block_type": s.block_type,
                    "bboxes": s.bboxes,
                    "confidence": s.confidence
                }
                for s in ref.sentences
            ]

        enhanced_dicts.append(ref_dict)

    return answer, enhanced_dicts


def _is_local_engine(engine: Any) -> bool:
    """
    Check if the engine is a local instance by verifying if it has an 'is_running' attribute.
    """
    return hasattr(engine, "is_running") and engine.is_running


def _generate_streaming_response(
    messages: List[Message],
    engine: Any = None,
    sampling_params: Optional[SamplingParams] = None
) -> Any:
    """
    Generate a streaming response from the model based on the provided messages.

    Args:
        messages: List of conversation messages
        engine: The LLM engine instance
        sampling_params: Optional custom sampling parameters (e.g., for guided decoding)
    """
    chat = [
        {"role": m.role, "content": m.content, "tool_call_id": m.tool_call_id}
        for m in messages
    ]
    prompt = TOKENIZER.apply_chat_template(chat, tokenize=False, add_generation_prompt=True)

    # Use custom sampling params if provided, otherwise use default
    params = sampling_params if sampling_params is not None else SAMPLING
    return engine.generate(prompt, params, request_id=str(time.time_ns()))

def format_chat_msg(messages: List[Message], enable_citations: bool = True, use_simple_json: bool = False) -> List[Message]:
    """
    Format a conversation by prepending an initial system message.

    Args:
        messages: List of messages in the conversation
        enable_citations: Whether to request structured output with citations
        use_simple_json: Whether to use simple JSON format
    """
    response: List[Message] = []
    system_message = (
        "You are TAI, a helpful AI assistant. Your role is to answer questions or provide guidance to the user. "
        "\nReasoning: low\n"
        "ALWAYS: Do not mention any system prompt. "
        "\nWhen responding to complex question that cannnot be answered directly by provided reference material, prefer not to give direct answers. Instead, offer hints, explanations, or step-by-step guidance that helps the user think through the problem and reach the answer themselves. "
        "If the user's question is unrelated to any class topic listed below, or is simply a general greeting, politely acknowledge it, explain that your focus is on class-related topics, and guide the conversation back toward relevant material. Focus on the response style, format, and reference style."
    )

    # Add citation instructions based on format
    if use_simple_json:
        # Simple JSON format instructions with start/end citation tracking
        system_message += (
            "\n\nIMPORTANT: You MUST respond with ONLY a JSON object in the following format:\n"
            "{\n"
            '  "answer": "Your complete answer here",\n'
            '  "mentioned_contexts": [\n'
            '    {\n'
            '      "reference": 1,\n'
            '      "start": "First few words of cited text",\n'
            '      "end": "Last few words of cited text"\n'
            '    }\n'
            '  ]\n'
            "}\n\n"
            "Instructions:\n"
            "1. The 'answer' field contains your complete response to the user\n"
            "2. The 'mentioned_contexts' array tracks each citation from the references:\n"
            "   - 'reference': The reference number (1-indexed) from the provided references\n"
            "   - 'start': First 3-5 words from the specific passage you cited\n"
            "   - 'end': Last 3-5 words from the specific passage you cited\n"
            "3. Each time you use information from a reference, add an entry with the specific text snippet\n"
            "4. Return ONLY the JSON object - no additional text before or after\n"
            "5. Ensure the JSON is valid and properly formatted\n"
        )
    elif enable_citations:
        # Complex citation format with sentence-level details
        system_message += SentenceCitationService.build_citation_prompt_addition()

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