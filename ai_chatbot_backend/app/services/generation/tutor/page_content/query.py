from typing import List
from uuid import UUID

from app.core.models.chat_completion import Message, PageContentParams
from app.services.query.vector_search import get_chunks_by_file_uuid
from app.services.generation.prompts.textchat.page_content import (
    PAGE_CONTENT_WITH_REFS,
    PAGE_CONTENT_NO_REFS,
)
from app.services.generation.prompts.textchat.page_content_html import (
    PAGE_CONTENT_HTML_WITH_REFS,
    PAGE_CONTENT_HTML_NO_REFS,
)
from app.services.generation.prompts.textchat.page_content_interactive import (
    PAGE_CONTENT_INTERACTIVE_WITH_REFS,
    PAGE_CONTENT_INTERACTIVE_NO_REFS,
)
from app.services.generation.prompts.slide_theme import CSS_CLASS_REFERENCE
from app.services.generation.prompts.explore_slide_system import (
    EXPLORE_SYSTEM_PROMPT_WITH_REFS,
    EXPLORE_SYSTEM_PROMPT_NO_REFS,
    EXPLORE_COMPONENT_REFERENCE,
)


def _resolve_class_name(course_code: str) -> str:
    """Resolve human-readable class name from course code."""
    try:
        from app.services.query.course_mapping import _get_pickle_and_class
        return _get_pickle_and_class(course_code)
    except (ValueError, KeyError):
        return course_code


def _fetch_chunk_texts(params: PageContentParams) -> List[str]:
    """Fetch chunk texts for each reference in params."""
    chunk_texts = []
    for ref in params.references:
        all_chunks = get_chunks_by_file_uuid(UUID(ref.file_uuid))
        for chunk in all_chunks:
            if chunk["index"] == ref.chunk_index:
                chunk_texts.append(chunk["chunk"])
                break
    return chunk_texts


def _build_user_message(params: PageContentParams, chunk_texts: List[str]) -> str:
    """Build the user message content (shared across all modes)."""
    user_content = f"<point>{params.point}</point>\n\n"
    user_content += f"<goal>{params.goal}</goal>\n\n"
    if params.requirements:
        user_content += f"<requirements>{params.requirements}</requirements>\n\n"
    if params.context:
        user_content += f"<context>{params.context}</context>\n\n"
    if chunk_texts:
        user_content += "<reference_materials>\n"
        for i, text in enumerate(chunk_texts, 1):
            user_content += f"--- Reference {i} ---\n{text}\n\n"
        user_content += "</reference_materials>"
    return user_content


def build_page_content_context(params: PageContentParams) -> List[Message]:
    """Build [system, user] messages for JSON block mode page content generation."""
    class_name = _resolve_class_name(params.course_code)
    chunk_texts = _fetch_chunk_texts(params)

    prompt = PAGE_CONTENT_WITH_REFS if chunk_texts else PAGE_CONTENT_NO_REFS
    system_prompt = prompt.format(course=params.course_code, class_name=class_name)

    return [
        Message(role="system", content=system_prompt),
        Message(role="user", content=_build_user_message(params, chunk_texts)),
    ]


def build_page_content_html_context(params: PageContentParams) -> List[Message]:
    """Build [system, user] messages for static HTML artifact mode."""
    class_name = _resolve_class_name(params.course_code)
    chunk_texts = _fetch_chunk_texts(params)

    prompt = PAGE_CONTENT_HTML_WITH_REFS if chunk_texts else PAGE_CONTENT_HTML_NO_REFS
    system_prompt = prompt.format(
        course=params.course_code,
        class_name=class_name,
        css_class_reference=CSS_CLASS_REFERENCE,
    )

    return [
        Message(role="system", content=system_prompt),
        Message(role="user", content=_build_user_message(params, chunk_texts)),
    ]


def build_page_content_interactive_context(params: PageContentParams) -> List[Message]:
    """Build [system, user] messages for interactive slide mode (complete HTML+CSS+JS)."""
    class_name = _resolve_class_name(params.course_code)
    chunk_texts = _fetch_chunk_texts(params)

    prompt = PAGE_CONTENT_INTERACTIVE_WITH_REFS if chunk_texts else PAGE_CONTENT_INTERACTIVE_NO_REFS
    system_prompt = prompt.format(course=params.course_code, class_name=class_name)

    return [
        Message(role="system", content=system_prompt),
        Message(role="user", content=_build_user_message(params, chunk_texts)),
    ]


def build_page_content_explore_context(params: PageContentParams) -> List[Message]:
    """Build [system, user] messages for explore mode (interactive textbook with reference tooltips).

    Unlike interactive mode where the AI generates the full HTML+CSS+JS,
    explore mode uses a FIXED CSS/JS framework. The AI only generates
    body HTML using a pre-defined component catalog. This separates
    design quality (deterministic) from content (AI-generated).
    """
    class_name = _resolve_class_name(params.course_code)
    chunk_texts = _fetch_chunk_texts(params)

    prompt = EXPLORE_SYSTEM_PROMPT_WITH_REFS if chunk_texts else EXPLORE_SYSTEM_PROMPT_NO_REFS
    system_prompt = prompt.format(
        course=params.course_code,
        class_name=class_name,
        component_reference=EXPLORE_COMPONENT_REFERENCE,
    )

    return [
        Message(role="system", content=system_prompt),
        Message(role="user", content=_build_user_message(params, chunk_texts)),
    ]
