"""
Combined pages pipeline: generate query -> OpenAI outline -> OpenAI page content.

Outline: OpenAI generates a depth-aware flat outline with inferred_depth,
topic, and pages (ordered list of teaching pages).
Page content: OpenAI generates block-based narration with sub_bullets, citations,
and reference open/close.

Pipelined: page 0 content generation starts as soon as the first page is parsed
from the streaming outline, rather than waiting for the entire outline.
"""
import asyncio
import json
import re
from typing import Any, AsyncIterator, List, Optional

from app.core.models.chat_completion import (
    CitationOpen,
    CitationClose,
    Done,
    GeneratePagesParams,
    OutlineComplete,
    PageBlockType,
    PageBullets,
    PageContentParams,
    PageDelta,
    PageError,
    PageReference,
    PageStart,
    Reference,
    ResponseReference,
    sse,
)
from app.services.generation.parser import (
    BlockStreamState,
    extract_answers_with_citations,
)


async def run_generate_pages_pipeline(
    params: GeneratePagesParams,
    openai_engine: Any,
    local_engine: Any,
) -> AsyncIterator[str]:
    """
    Combined pipeline: outline generation (OpenAI) -> per-page content (OpenAI).

    For each page, OpenAI generates block-based JSON with:
      - sub_bullets: knowledge sub-points for the page
      - blocks: narration with integrated citation open/close
    """
    from app.services.generation.tutor.query import build_tutor_context
    from app.services.generation.tutor.generate import call_tutor_model
    from app.services.generation.tutor.page_content.query import build_page_content_context
    from app.services.generation.tutor.page_content.generate import call_page_content_openai

    # === Step 1: Build context (RAG + query reformulation) ===
    context = await build_tutor_context(
        messages=params.messages,
        user_focus=None,
        answer_content=None,
        problem_content=None,
        course=params.course_code,
        engine=openai_engine,
        sid=params.sid,
        timer=None,
        audio_response=False,
    )

    # === Step 2: Emit all retrieved references upfront ===
    references = _build_references_from_list(context.reference_list)
    if references:
        yield sse(ResponseReference(references=references))

    # === Step 3: Start outline stream ===
    raw_stream = await call_tutor_model(
        context.messages, openai_engine, stream=True,
        audio_response=False, course=params.course_code,
        outline_mode=True,
    )

    # === Step 4: Background task — collect outline, push leaf nodes to queue ===
    node_queue: asyncio.Queue = asyncio.Queue()
    outline_holder: dict = {}  # mutable container for the parsed outline

    async def _collect_outline():
        outline_text = ""
        parsed_count = 0
        metadata_extracted = False
        async for chunk in raw_stream:
            if not hasattr(chunk, "choices") or not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            content = getattr(delta, "content", None)
            if not content:
                continue
            outline_text += content

            # Detect outline metadata early (before nodes finish)
            if not metadata_extracted:
                metadata = _extract_outline_metadata(outline_text)
                if metadata:
                    outline_holder["data"] = metadata
                    metadata_extracted = True

            # Try to extract newly completed pages
            new_leaves = _extract_new_pages(outline_text, parsed_count)
            for node in new_leaves:
                await node_queue.put(node)
                parsed_count += 1

        # Store the full parsed outline (overwrites early metadata with complete data)
        parsed = _parse_outline(outline_text)
        if parsed:
            outline_holder["data"] = parsed
            print("\n" + "=" * 60)
            print("[DEBUG] Full parsed outline:")
            print("=" * 60)
            print(json.dumps(parsed, indent=2, ensure_ascii=False))
            print("=" * 60 + "\n")
        elif not metadata_extracted:
            print(f"[ERROR] Failed to parse outline JSON: {outline_text[:500]}")
            outline_holder["error"] = True

        # Sentinel: no more nodes
        await node_queue.put(None)

    outline_task = asyncio.create_task(_collect_outline())

    # === Step 5: Generate pages as leaf nodes arrive from the queue ===
    page_idx = 1
    outline_emitted = False

    while True:
        node = await node_queue.get()
        if node is None:
            break

        try:
            page_refs = _resolve_page_references(
                node.get("reference_ids", []),
                context.reference_list,
            )

            page_params = PageContentParams(
                point=node["title"],
                purpose=node["purpose"],
                effort=node.get("effort", ""),
                references=page_refs,
                course_code=params.course_code,
            )

            yield sse(PageStart(page_index=page_idx, point=node["title"], purpose=node["purpose"]))

            # --- Generate page content via OpenAI (block-based JSON, streaming) ---
            page_messages = build_page_content_context(page_params)
            page_stream = await call_page_content_openai(
                page_messages, openai_engine, course=params.course_code
            )

            page_text = ""
            sub_bullets_emitted = False
            block_state = BlockStreamState()
            seq = 0
            has_content = False

            async for chunk in page_stream:
                # Check if outline finished during page generation
                if not outline_emitted and outline_holder.get("data"):
                    yield sse(OutlineComplete(outline=outline_holder["data"]))
                    outline_emitted = True

                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                content = getattr(delta, "content", None)
                if not content:
                    continue

                page_text += content

                # Try to extract sub_bullets early (before blocks arrive)
                if not sub_bullets_emitted:
                    sub_bullets = _extract_sub_bullets(page_text)
                    if sub_bullets is not None:
                        yield sse(PageBullets(page_index=page_idx, sub_bullets=sub_bullets))
                        sub_bullets_emitted = True

                # Incrementally parse blocks for citation events + text deltas
                events = extract_answers_with_citations(page_text, block_state)
                for evt in events:
                    if evt.block_type is not None:
                        yield sse(PageBlockType(page_index=page_idx, block_type=evt.block_type))
                    if evt.citation_open is not None:
                        yield sse(CitationOpen(
                            citation_id=evt.citation_open.citation_id,
                            quote_text=evt.citation_open.quote_text or None,
                        ))
                    if evt.text_delta is not None:
                        yield sse(PageDelta(page_index=page_idx, seq=seq, text=evt.text_delta))
                        seq += 1
                        has_content = True
                    if evt.citation_close is not None:
                        yield sse(CitationClose(citation_id=evt.citation_close))

            # Final parse after stream completes — flush remaining events
            if page_text:
                events = extract_answers_with_citations(page_text, block_state)
                for evt in events:
                    if evt.block_type is not None:
                        yield sse(PageBlockType(page_index=page_idx, block_type=evt.block_type))
                    if evt.citation_open is not None:
                        yield sse(CitationOpen(
                            citation_id=evt.citation_open.citation_id,
                            quote_text=evt.citation_open.quote_text or None,
                        ))
                    if evt.text_delta is not None:
                        yield sse(PageDelta(page_index=page_idx, seq=seq, text=evt.text_delta))
                        seq += 1
                        has_content = True
                    if evt.citation_close is not None:
                        yield sse(CitationClose(citation_id=evt.citation_close))

            # Emit sub_bullets if not yet emitted (fallback: parse complete JSON)
            if not sub_bullets_emitted and page_text:
                sub_bullets = _extract_sub_bullets(page_text)
                if sub_bullets is not None:
                    yield sse(PageBullets(page_index=page_idx, sub_bullets=sub_bullets))

            # Check outline again after page generation
            if not outline_emitted and outline_holder.get("data"):
                yield sse(OutlineComplete(outline=outline_holder["data"]))
                outline_emitted = True

            if not has_content:
                print(f"[WARNING] Page {page_idx} produced no content tokens")
                yield sse(PageError(page_index=page_idx, error="Model produced no content for this page"))

        except Exception as e:
            print(f"[ERROR] Page {page_idx} generation failed: {e}")
            yield sse(PageError(page_index=page_idx, error=str(e)))

        page_idx += 1

    # === Step 6: Ensure outline.complete is emitted ===
    if not outline_emitted:
        if not outline_task.done():
            await outline_task
        if outline_holder.get("data"):
            yield sse(OutlineComplete(outline=outline_holder["data"]))
        elif outline_holder.get("error"):
            yield sse(PageError(page_index=-1, error="Failed to parse outline JSON"))

    yield sse(Done())
    yield "data: [DONE]\n\n"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_outline_metadata(text: str) -> Optional[dict]:
    """
    Extract inferred_depth + topic from partial outline JSON (before nodes finish).

    The outline JSON streams: thinking → inferred_depth → outline { topic → nodes[] }.
    Once we have inferred_depth and topic, we can emit early metadata for the
    OutlineComplete event, without waiting for all node details.
    """
    depth_match = re.search(r'"inferred_depth"\s*:\s*"(minimal|standard)"', text)
    topic_match = re.search(r'"topic"\s*:\s*"((?:[^"\\]|\\.)*)"', text)
    if not depth_match or not topic_match:
        return None

    return {
        "thinking": "",
        "inferred_depth": depth_match.group(1),
        "outline": {
            "topic": topic_match.group(1),
            "pages": [],  # not yet available
        },
    }


def _extract_sub_bullets(text: str) -> Optional[list]:
    """
    Extract the sub_bullets array from partial or complete page content JSON.

    Returns the list of sub-bullet strings if found and complete, else None.
    sub_bullets appears before blocks in the JSON, so it's available early in the stream.
    """
    # Try complete JSON parse first
    try:
        data = json.loads(text)
        if isinstance(data, dict) and "sub_bullets" in data:
            return data["sub_bullets"]
    except json.JSONDecodeError:
        pass

    # Streaming: try to extract the sub_bullets array from partial JSON
    match = re.search(r'"sub_bullets"\s*:\s*(\[.*?\])', text, re.DOTALL)
    if match:
        try:
            arr = json.loads(match.group(1))
            if isinstance(arr, list):
                return arr
        except json.JSONDecodeError:
            pass

    return None


def _extract_new_pages(text: str, already_parsed: int) -> List[dict]:
    """
    Incrementally extract complete page objects from partial outline JSON.

    Tracks brace depth (with string/escape awareness) to detect complete
    {...} objects inside the "pages" array. All pages are returned in order.
    """
    # Find the start of the pages array
    match = re.search(r'"pages"\s*:\s*\[', text)
    if not match:
        return []

    start = match.end()
    all_pages: List[dict] = []
    depth = 0
    obj_start = None
    in_string = False
    escape = False

    for i in range(start, len(text)):
        ch = text[i]

        if escape:
            escape = False
            continue
        if ch == '\\' and in_string:
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue

        if ch == '{':
            if depth == 0:
                obj_start = i
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0 and obj_start is not None:
                try:
                    obj = json.loads(text[obj_start:i + 1])
                    if "page_id" in obj and "title" in obj:
                        all_pages.append(obj)
                except json.JSONDecodeError:
                    pass
                obj_start = None

    # Return only newly parsed pages
    return all_pages[already_parsed:]



def _parse_outline(text: str) -> Optional[dict]:
    """Parse outline JSON from model output, handling markdown code fences."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*\n?", "", text)
        text = re.sub(r"\n?```\s*$", "", text)
    try:
        data = json.loads(text)
        if (isinstance(data, dict)
                and "outline" in data
                and "pages" in data.get("outline", {})):
            return data
    except json.JSONDecodeError:
        pass
    return None


def _build_references_from_list(reference_list: list) -> List[Reference]:
    """Build Reference objects from all retrieved references."""
    references = []
    for i, ref_tuple in enumerate(reference_list, 1):
        info_path, url, file_path, file_uuid, chunk_index = ref_tuple
        references.append(Reference(
            reference_idx=i,
            info_path=info_path,
            url=url,
            file_path=file_path,
            file_uuid=file_uuid,
            chunk_index=chunk_index,
        ))
    return references


def _resolve_page_references(ref_ids: list, reference_list: list) -> List[PageReference]:
    """Convert outline reference integer IDs to PageReference objects for page content."""
    page_refs = []
    max_idx = len(reference_list)
    for ref_id in ref_ids:
        try:
            idx = int(ref_id)
        except (TypeError, ValueError):
            continue
        if 1 <= idx <= max_idx:
            _, _, _, file_uuid, chunk_index = reference_list[idx - 1]
            page_refs.append(PageReference(
                file_uuid=file_uuid,
                chunk_index=chunk_index,
            ))
    return page_refs


# ---------------------------------------------------------------------------
# Speech script generation (for TTS narration of pages)
# ---------------------------------------------------------------------------

PAGE_SPEECH_SYSTEM_PROMPT = """\
You are TAI, a university tutor for {course_code}.
You are speaking aloud to a student, explaining a topic page by page.
Generate ONLY what you would say — natural, conversational, like a real lecture.

Rules:
- No markdown, no code fences, no bullet lists, no brackets.
- When referencing code, describe it in words (e.g., "a function called make_adder that takes n").
- Vary your pacing and transitions naturally.
- Use the teaching purpose as your guide for HOW to explain.
- Use the bullet points as your guide for WHAT to cover.
- Keep it focused — this is one page of a multi-page lesson.
- Do NOT repeat content that was already covered in a previous page's narration."""

INTRO_SPEECH_SYSTEM_PROMPT = """\
You are TAI, a university tutor for {course_code}.
You are about to begin a spoken lesson for a student.
Generate ONLY what you would say — natural, conversational, like a real lecture.

Rules:
- No markdown, no code fences, no bullet lists, no brackets.
- Start by acknowledging the student's question and naturally transition into your answer.
- Briefly preview what the lesson will cover.
- Keep it concise — this is just the opening, not the full lesson."""


async def generate_speech_script(
    engine: Any,
    course_code: str,
    user_content: str,
    system_prompt: Optional[str] = None,
    temperature: float = 0.7,
    max_tokens: int = 800,
) -> str:
    """Generate a speech script from the model, returning the full text."""
    system = system_prompt or PAGE_SPEECH_SYSTEM_PROMPT.format(course_code=course_code)
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user_content},
    ]
    stream = await engine(
        user_content,
        messages=messages,
        stream=True,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    full_text = ""
    async for chunk in stream:
        if chunk.choices:
            token = chunk.choices[0].delta.content
            if token:
                full_text += token
    return full_text


async def generate_intro_speech(
    engine: Any,
    course_code: str,
    student_question: str,
    topic: str,
    total_pages: int,
    page_titles: List[str],
) -> str:
    """
    Generate the intro (page 0) speech that transitions from the student's
    question into the lesson overview.

    Returns:
        The generated intro speech text.
    """
    titles_text = "\n".join(f"- {t}" for t in page_titles)
    user_content = (
        f'The student asked: "{student_question}"\n'
        f'Lesson topic: "{topic}" ({total_pages} pages)\n'
        f"Pages:\n{titles_text}\n\n"
        f"Generate a brief spoken intro that acknowledges the student's question, "
        f"transitions naturally into your answer, and previews what the lesson will cover."
    )
    system = INTRO_SPEECH_SYSTEM_PROMPT.format(course_code=course_code)
    return await generate_speech_script(
        engine, course_code, user_content, system_prompt=system,
    )


async def generate_page_speech(
    engine: Any,
    course_code: str,
    page_idx: int,
    page_title: str,
    purpose: str,
    sub_bullets: list,
    total_pages: int,
    previous_titles: List[str],
    previous_speech: str = "",
) -> str:
    """
    Generate a TTS speech script for a single content page.

    Speech is generated sequentially: each page waits for the previous page's
    speech to complete, and the previous page's speech content is included in
    the prompt to avoid repetition.

    Args:
        engine: LLM engine callable.
        course_code: Course identifier.
        page_idx: Zero-based page index.
        page_title: Student-facing page title.
        purpose: Teaching purpose/approach for this page.
        sub_bullets: List of sub-bullet dicts or strings.
        total_pages: Total number of pages in the lesson.
        previous_titles: Titles of pages that came before this one.
        previous_speech: The speech text generated for the immediately
            preceding page. Used to avoid repeating the same content.

    Returns:
        The generated speech text.
    """
    bullet_text = "\n".join(
        f"- {sb.get('point', sb) if isinstance(sb, dict) else sb}"
        for sb in sub_bullets
    )
    prev_pages = (
        ", ".join(f'"{t}"' for t in previous_titles)
        if previous_titles
        else "(this is the first page)"
    )

    prev_speech_section = ""
    if previous_speech:
        prev_speech_section = (
            f"\n--- What was said on the previous page (do NOT repeat this) ---\n"
            f"{previous_speech}\n"
            f"--- End of previous page narration ---\n"
        )

    user_content = (
        f'Page {page_idx + 1} of {total_pages}: "{page_title}"\n'
        f"Teaching approach: {purpose}\n"
        f"Key points to cover:\n{bullet_text}\n"
        f"Previous pages covered: {prev_pages}\n"
        f"{prev_speech_section}\n"
        f"Generate what you would say aloud to teach this page. "
        f"Do not repeat what was already said on the previous page."
    )
    return await generate_speech_script(engine, course_code, user_content)
