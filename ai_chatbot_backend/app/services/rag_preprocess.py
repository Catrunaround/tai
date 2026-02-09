# Standard python libraries
import time
from typing import Any, Optional, Tuple, List, Dict
from uuid import UUID
# Third-party libraries
from openai import OpenAI, AsyncOpenAI
# Local libraries
from app.services.rag_retriever import get_reference_documents, get_chunks_by_file_uuid, get_sections_by_file_uuid, get_file_related_documents
from app.services.rag_postprocess import extract_channels
from app.services.request_timer import RequestTimer
from app.prompts import modes
from app.config import settings

# Query reformulator prompt (inlined from rag.py)
_QUERY_REFORMULATOR_PROMPT = (
    "You are a query reformulator for a RAG system. "
    "Given the user message and the memory synopsis of the current conversation as well as the file context if any, "
    "rewrite the latest user request as a single, "
    "self-contained question for document retrieval. "
    "Resolve pronouns and references using context, include relevant constraints "
    "(dates, versions, scope), and avoid adding facts not in the history. "
    "Return only the rewritten query as question in plain text—no quotes, no extra text."
    "# Valid channels: analysis, commentary, final. Channel must be included for every message."
    "Calls to these tools must go to the commentary channel: 'functions'.<|end|>"
)


async def build_retrieval_query(user_message: str, memory_synopsis: Any, engine: Any, file_sections: Any = None, excerpt: Any = None) -> str:
    """
    Reformulate the latest user request into a single self-contained query string,
    based on the full chat history (user + assistant messages).
    Returns plain text with no quotes or extra formatting.
    """
    # Prepare the chat history for the model
    system_prompt = _QUERY_REFORMULATOR_PROMPT

    # If no context is provided, return the original user message
    if not memory_synopsis and not file_sections and not excerpt:
        return user_message

    request_parts = []

    if memory_synopsis:
        request_parts.append(f"Memory Synopsis:\n{memory_synopsis}\n")

    if file_sections or excerpt:
        request_parts.append(f"File Context:\n")

    if file_sections:
        request_parts.append(f"The user is looking at this file which has these sections: {file_sections}\n")

    if excerpt:
        request_parts.append(f"The user is focused on the following part of the file: {excerpt}\n")

    request_parts.append(f"User Message:\n{user_message}\n")

    request_content = "\n".join(request_parts)

    # Check if engine is OpenAI client
    if isinstance(engine, (OpenAI, AsyncOpenAI)):
        chat = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": request_content}
        ]
        # Generate the query using the OpenAI API
        response = await engine.chat.completions.create(
            model=settings.vllm_chat_model,
            messages=chat,
            temperature=0.6,
            top_p=0.95,
            max_tokens=500,
            extra_body={"top_k": 20, "min_p": 0}
        )
        # vLLM with --reasoning-parser separates reasoning_content from content
        # Use content directly (final response without thinking)
        text = response.choices[0].message.content or ""
        print(f"[INFO] Generated RAG-Query: {text.strip()}")
        return text.strip()
    else:
        # Fallback for remote/mock pipelines
        return user_message


def build_augmented_prompt(
        user_message: str,
        course: str,
        threshold: float,
        rag: bool,
        top_k: int = 7,
        query_message: str = "",
        reference_list: List[Dict] = None,
        problem_content: Optional[str] = None,
        answer_content: Optional[str] = None,
        audio_response: bool = False,
        tutor_mode: bool = True,
        timer: Optional[RequestTimer] = None
) -> Tuple[str, List[Dict], str]:
    """
    Build an augmented prompt by retrieving reference documents.

    4-Mode System:
    - Chat Tutor (tutor_mode=True, audio_response=False): JSON with citations-first
    - Chat Regular (tutor_mode=False, audio_response=False): Plain Markdown
    - Voice Tutor (tutor_mode=True, audio_response=True): JSON with unreadable property
    - Voice Regular (tutor_mode=False, audio_response=True): Plain speakable text

    Returns:
      - modified_message: the augmented instruction prompt.
      - reference_list: list of reference URLs for JSON output.
      - system_add_message: additional system message content.
    """
    # Practice mode has its own message format
    if answer_content and problem_content:
        user_message = (
            f"Course problem:\n{problem_content}\n"
            f"Answer attempted by user:\n{answer_content}\n"
            f"Instruction: {user_message}"
        )
    # Print parameter information
    print('\n Course: \n', course, '\n')
    print("\nUser Question: \n", user_message, "\n")
    print('time of the day:', time.strftime('%Y-%m-%d %H:%M:%S', time.localtime()), '\n')
    # No need to retrieve documents if rag is False
    if not rag:
        return user_message, []
    # If query_message is not provided, use user_message
    if not query_message:
        query_message = user_message
    # Retrieve reference documents based on the query
    (
        top_chunk_uuids, top_docs, top_urls, similarity_scores, top_files, top_refs, top_titles,
        top_file_uuids, top_chunk_idxs
    ), class_name = get_reference_documents(query_message, course, top_k=top_k, timer=timer)
    # Prepare the insert document and reference list
    insert_document = ""
    reference_list = reference_list or []
    n = len(reference_list)
    for i in range(len(top_docs)):
        if similarity_scores[i] > threshold:
            n += 1
            file_path = top_files[i]
            file_uuid = top_file_uuids[i]
            chunk_index = top_chunk_idxs[i]
            topic_path = top_refs[i]
            url = top_urls[i] if top_urls[i] else ""
            insert_document += (
                f'Reference Number: {n}\n'
                f"Directory Path to reference file to tell what file is about: {file_path}\n"
                f"Topic Path of chunk in file to tell the topic of chunk: {topic_path}\n"
                f'Document: {top_docs[i]}\n\n'
            )
            reference_list.append([topic_path, url, file_path, file_uuid, chunk_index])

    # Get mode configuration - single source of truth
    config = modes.get_mode_config(tutor_mode, audio_response)

    # Create modified message based on whether documents were inserted
    if not insert_document or n == 0:
        print("[INFO] No relevant documents found above the similarity threshold.")
        addendum = config.system_addendum_no_refs
        modified_message = ""
    else:
        print("[INFO] Relevant documents found and inserted into the prompt.")
        addendum = config.system_addendum_with_refs
        modified_message = f"{insert_document}\n---\n"
    # Resolve {course}/{class_name} placeholders in the addendum
    if isinstance(addendum, dict):
        # Template-based: resolve placeholders in each value
        system_add_message = {
            k: v.format(course=course, class_name=class_name) for k, v in addendum.items()
        }
    else:
        # Legacy string format
        system_add_message = addendum.format(course=course, class_name=class_name)
    # Append user instruction to the modified message
    if not (answer_content and problem_content):
        modified_message += f"Instruction: {user_message}"
    else:
        modified_message += user_message
    # Return the final modified message and reference list
    return modified_message, reference_list, system_add_message


def build_file_augmented_context(
        file_uuid: UUID,
        selected_text: Optional[str] = None,
        index: Optional[float] = None,
) -> Tuple[str, str, str, List[Dict]]:
    """
    Build an augmented context for file-based chat by retrieving reference documents.
    Returns:
    - augmented_context: the augmented context for the file.
    - focused_chunk: the chunk of text the user is currently focused on.
    - file_content: the full content of the file.
    - sections: list of sections in the file.
    """
    # Get file content by file UUID
    chunks = get_chunks_by_file_uuid(file_uuid)
    sections = get_sections_by_file_uuid(file_uuid)
    file_content = " ".join(chunk["chunk"] for chunk in chunks)

    augmented_context = (
        f"The user is looking at this file to give the instruction: \n{file_content}\n---\n"
    )

    focused_chunk = ""
    if index:
        # Find chunks closest to the given index
        closest_chunks = []
        if chunks:
            # Calculate distances and find minimum distance
            min_distance = min(abs(chunk['index'] - index) for chunk in chunks)
            # Get all chunks with minimum distance
            closest_chunks = [chunk for chunk in chunks if abs(chunk['index'] - index) == min_distance]
            # Already sorted by chunk_index, so closest_chunks are in order
        focused_chunk = ' '.join(chunk['chunk'] for chunk in closest_chunks)
        augmented_context += f"The user is focused on the following part of the file: {focused_chunk}\n\n"

    if selected_text:
        augmented_context += f"The user has selected the following text in the file:\n\n{selected_text}\n\n"

    return augmented_context, file_content, focused_chunk, sections
