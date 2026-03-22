"""
Combined pages pipeline: generate query -> OpenAI outline -> local vLLM page content.

Outline (page 0 / plan): OpenAI generates a flat outline with
topic and pages (ordered list of teaching pages).
Page content (page 1+): Local vLLM generates block-based narration with
block-based content with citations and reference open/close.

Pipelined: page 0 content generation starts as soon as the first page is parsed
from the streaming outline, rather than waiting for the entire outline.
"""
import asyncio
import json
import re
from typing import Any, AsyncIterator, List, Optional

from app.core.models.chat_completion import (
    BlockClose,
    BlockOpen,
    CitationClose,
    CitationOpen,
    Done,
    GeneratePagesParams,
    OutlineComplete,
    PageClose,
    PageContentParams,
    PageDelta,
    PageError,
    PageOpen,
    PageReference,
    PageSpeech,
    PageSpeechDelta,
    PageSpeechDone,
    Reference,
    ResponseReference,
    SpeechCitation,
    sse,
)
from app.services.generation.parser import (
    BlockStreamState,
    extract_answers,
    extract_answers_with_citations,
)


async def run_generate_pages_pipeline(
    params: GeneratePagesParams,
    openai_engine: Any,
    local_engine: Any,
    speech_engine: Any = None,
) -> AsyncIterator[str]:
    """
    Combined pipeline: outline generation (OpenAI) -> per-page content (local vLLM)
    -> sequential speech generation per page.

    For each page, local vLLM generates block-based JSON with:
      - blocks: slide content with citations
      - blocks: narration with integrated citation open/close

    Speech is generated sequentially after each page's content is complete.
    Each page's speech prompt includes the previous page's speech text to
    avoid repetition.  Page 0 (intro) speech transitions from the student's
    question into the lesson overview.

    Args:
        speech_engine: Engine used for speech script generation.
            Defaults to openai_engine if not provided.
    """
    from app.services.generation.tutor.query import build_tutor_context
    from app.services.generation.tutor.generate import call_tutor_model
    from app.services.generation.tutor.page_content.query import build_page_content_context
    from app.services.generation.tutor.page_content.generate import call_page_content_local

    if speech_engine is None:
        speech_engine = openai_engine

    # Extract the student's original question (last user message)
    student_question = ""
    for msg in reversed(params.messages):
        if msg.role == "user":
            student_question = msg.content
            break

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

    # === Step 2.5: Generate intro speech (only needs student question) ===
    intro_text = await generate_intro_speech(
        engine=speech_engine,
        course_code=params.course_code,
        student_question=student_question,
    )
    yield sse(PageSpeech(page_index=0, speech_text=intro_text))
    last_speech_text = intro_text

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

    # --- Speech state: sequential generation with previous-page context ---
    # last_speech_text is initialized to intro speech (generated in Step 2.5)
    # Buffer pages whose content finished before outline was available
    speech_buffer: List[dict] = []  # [{page_idx, title, goal, page_content, citations}, ...]

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
                goal=node["goal"],
                requirements=node.get("requirements", ""),
                references=page_refs,
                course_code=params.course_code,
            )

            yield sse(PageOpen(page_index=page_idx, point=node["title"], goal=node["goal"]))

            # --- Generate page content via local vLLM (block-based JSON, streaming) ---
            page_messages = build_page_content_context(page_params)
            page_stream = await call_page_content_local(
                page_messages, local_engine
            )

            page_text = ""
            block_state = BlockStreamState()
            seq = 0
            has_content = False
            block_is_open = False  # track whether a block.open has been emitted
            # For local→global reference mapping
            page_ref_ids = [int(r) for r in node.get("reference_ids", []) if _safe_int(r) is not None]
            active_global_ref: Optional[int] = None  # currently open global reference_idx
            # Collect citation events for PageSpeech (no longer emitted during page streaming)
            page_citations: list[SpeechCitation] = []

            async for chunk in page_stream:
                # Check if outline finished during page generation
                if not outline_emitted and outline_holder.get("data"):
                    yield sse(OutlineComplete(outline=outline_holder["data"]))
                    outline_emitted = True

                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                content = getattr(delta, "content", None)
                # Fallback: use reasoning_content if content is empty (thinking mode leak)
                if not content:
                    content = getattr(delta, "reasoning_content", None)
                if not content:
                    continue

                page_text += content

                # Incrementally parse blocks for text deltas + block types.
                # Citation events are emitted as SSE AND collected for PageSpeech.
                events = extract_answers_with_citations(page_text, block_state)
                for evt in events:
                    if evt.block_type is not None:
                        # Close previous block before opening a new one
                        if block_is_open:
                            yield sse(BlockClose(page_index=page_idx))
                        yield sse(BlockOpen(page_index=page_idx, block_type=evt.block_type))
                        block_is_open = True
                    if evt.citation_open is not None:
                        ref_idx, ref_path = _resolve_reference(
                            evt.citation_open.citation_id, page_ref_ids,
                            context.reference_list,
                        )
                        yield sse(CitationOpen(
                            citation_id=evt.citation_open.citation_id,
                            quote_text=evt.citation_open.quote_text or None,
                            page_index=page_idx,
                            reference_idx=ref_idx,
                            file_path=ref_path,
                        ))
                        page_citations.append(SpeechCitation(
                            action="open",
                            citation_id=evt.citation_open.citation_id,
                            char_offset=0,  # placeholder; real offset computed in _parse_speech_citations
                            quote_text=evt.citation_open.quote_text or None,
                            reference_idx=ref_idx,
                            file_path=ref_path,
                        ))
                        if ref_idx is not None:
                            active_global_ref = ref_idx
                    if evt.text_delta is not None:
                        yield sse(PageDelta(page_index=page_idx, seq=seq, text=evt.text_delta))
                        seq += 1
                        has_content = True
                    if evt.citation_close is not None:
                        yield sse(CitationClose(
                            citation_id=evt.citation_close,
                            page_index=page_idx,
                            reference_idx=active_global_ref,
                        ))
                        page_citations.append(SpeechCitation(
                            action="close",
                            citation_id=evt.citation_close,
                            char_offset=0,  # placeholder
                            reference_idx=active_global_ref,
                        ))
                        active_global_ref = None

            # Final parse after stream completes — flush remaining events
            if page_text:
                events = extract_answers_with_citations(page_text, block_state)
                for evt in events:
                    if evt.block_type is not None:
                        if block_is_open:
                            yield sse(BlockClose(page_index=page_idx))
                        yield sse(BlockOpen(page_index=page_idx, block_type=evt.block_type))
                        block_is_open = True
                    if evt.citation_open is not None:
                        ref_idx, ref_path = _resolve_reference(
                            evt.citation_open.citation_id, page_ref_ids,
                            context.reference_list,
                        )
                        yield sse(CitationOpen(
                            citation_id=evt.citation_open.citation_id,
                            quote_text=evt.citation_open.quote_text or None,
                            page_index=page_idx,
                            reference_idx=ref_idx,
                            file_path=ref_path,
                        ))
                        page_citations.append(SpeechCitation(
                            action="open",
                            citation_id=evt.citation_open.citation_id,
                            char_offset=0,  # placeholder; real offset computed in _parse_speech_citations
                            quote_text=evt.citation_open.quote_text or None,
                            reference_idx=ref_idx,
                            file_path=ref_path,
                        ))
                        if ref_idx is not None:
                            active_global_ref = ref_idx
                    if evt.text_delta is not None:
                        yield sse(PageDelta(page_index=page_idx, seq=seq, text=evt.text_delta))
                        seq += 1
                        has_content = True
                    if evt.citation_close is not None:
                        yield sse(CitationClose(
                            citation_id=evt.citation_close,
                            page_index=page_idx,
                            reference_idx=active_global_ref,
                        ))
                        page_citations.append(SpeechCitation(
                            action="close",
                            citation_id=evt.citation_close,
                            char_offset=0,  # placeholder
                            reference_idx=active_global_ref,
                        ))
                        active_global_ref = None

            # Close the last block if one is still open
            if block_is_open:
                yield sse(BlockClose(page_index=page_idx))

            # Extract page content text for speech generation
            page_content_text = extract_answers(page_text) if page_text else ""

            # Check outline again after page generation
            if not outline_emitted and outline_holder.get("data"):
                yield sse(OutlineComplete(outline=outline_holder["data"]))
                outline_emitted = True

            # Fallback: if parser found nothing but model DID produce text,
            # the output is likely raw markdown (structured json not enforced).
            # Emit the raw text as a single PageDelta inside a readable block.
            if not has_content and page_text.strip():
                print(f"[INFO] Page {page_idx}: structured json not enforced, falling back to raw markdown")
                yield sse(BlockOpen(page_index=page_idx, block_type="readable"))
                yield sse(PageDelta(page_index=page_idx, seq=seq, text=page_text.strip()))
                yield sse(BlockClose(page_index=page_idx))
                seq += 1
                has_content = True

            if not has_content:
                print(f"[WARNING] Page {page_idx} produced no content tokens")
                yield sse(PageError(page_index=page_idx, error="Model produced no content for this page"))

            # Emit page.close to signal page content is finalized
            yield sse(PageClose(page_index=page_idx))

            # Build citation metadata for speech generation.
            # Prefer content-parser citations; fall back to outline-derived metadata.
            speech_meta = page_citations if page_citations else _build_page_citation_meta(
                page_ref_ids, context.reference_list,
            )

            # --- Speech generation (sequential, after page content is done) ---
            page_speech_data = {
                "page_idx": page_idx,
                "title": node["title"],
                "goal": node.get("goal", ""),
                "page_content": page_content_text,
                "citations": speech_meta,
            }

            if not outline_emitted:
                # Outline not yet available — buffer for later
                speech_buffer.append(page_speech_data)
            else:
                # Outline available — flush any buffered speeches first
                for buf in speech_buffer:
                    outline_obj = outline_holder["data"].get("outline", {})
                    all_titles = [p["title"] for p in outline_obj.get("pages", [])]
                    total_pages = len(all_titles)
                    prev_titles = all_titles[:buf["page_idx"] - 1] if buf["page_idx"] > 1 else []
                    async for speech_evt in stream_page_speech(
                        engine=speech_engine,
                        course_code=params.course_code,
                        page_index=buf["page_idx"],
                        page_idx=buf["page_idx"] - 1,
                        page_title=buf["title"],
                        goal=buf["goal"],
                        page_content=buf["page_content"],
                        total_pages=total_pages,
                        previous_titles=prev_titles,
                        previous_speech=last_speech_text,
                        page_citations=buf["citations"],
                    ):
                        yield speech_evt
                        # Capture full_text from the done event for next page's context
                        if '"page.speech.done"' in speech_evt:
                            done_data = json.loads(speech_evt[len("data: "):].strip())
                            last_speech_text = done_data.get("full_text", "")
                speech_buffer = []

                # Generate speech for current page
                outline_obj = outline_holder["data"].get("outline", {})
                all_titles = [p["title"] for p in outline_obj.get("pages", [])]
                total_pages = len(all_titles)
                prev_titles = all_titles[:page_idx - 1] if page_idx > 1 else []
                async for speech_evt in stream_page_speech(
                    engine=speech_engine,
                    course_code=params.course_code,
                    page_index=page_idx,
                    page_idx=page_idx - 1,
                    page_title=node["title"],
                    goal=node.get("goal", ""),
                    page_content=page_content_text,
                    total_pages=total_pages,
                    previous_titles=prev_titles,
                    previous_speech=last_speech_text,
                    page_citations=speech_meta,
                ):
                    yield speech_evt
                    if '"page.speech.done"' in speech_evt:
                        done_data = json.loads(speech_evt[len("data: "):].strip())
                        last_speech_text = done_data.get("full_text", "")

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
            outline_emitted = True
        elif outline_holder.get("error"):
            yield sse(PageError(page_index=-1, error="Failed to parse outline JSON"))

    # === Step 7: Flush any remaining buffered speeches ===
    if speech_buffer and outline_emitted:
        for buf in speech_buffer:
            outline_obj = outline_holder["data"].get("outline", {})
            all_titles = [p["title"] for p in outline_obj.get("pages", [])]
            total_pages = len(all_titles)
            prev_titles = all_titles[:buf["page_idx"] - 1] if buf["page_idx"] > 1 else []
            async for speech_evt in stream_page_speech(
                engine=speech_engine,
                course_code=params.course_code,
                page_index=buf["page_idx"],
                page_idx=buf["page_idx"] - 1,
                page_title=buf["title"],
                goal=buf["goal"],
                page_content=buf["page_content"],
                total_pages=total_pages,
                previous_titles=prev_titles,
                previous_speech=last_speech_text,
                page_citations=buf["citations"],
            ):
                yield speech_evt
                if '"page.speech.done"' in speech_evt:
                    done_data = json.loads(speech_evt[len("data: "):].strip())
                    last_speech_text = done_data.get("full_text", "")

    yield sse(Done())
    yield "data: [DONE]\n\n"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_outline_metadata(text: str) -> Optional[dict]:
    """
    Extract topic from partial outline JSON (before pages finish).

    The outline JSON streams: outline { topic → pages[] }.
    Once we have the topic, we can emit early metadata for the
    OutlineComplete event, without waiting for all page details.
    """
    topic_match = re.search(r'"topic"\s*:\s*"((?:[^"\\]|\\.)*)"', text)
    if not topic_match:
        return None

    return {
        "outline": {
            "topic": topic_match.group(1),
            "pages": [],  # not yet available
        },
    }


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


def _safe_int(val) -> Optional[int]:
    """Try to convert a value to int, return None on failure."""
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


def _build_page_citation_meta(
    page_ref_ids: List[int],
    reference_list: list,
) -> list[SpeechCitation]:
    """Build citation metadata from outline-assigned reference_ids.

    This provides the speech generator with reference info even when the
    content parser produces no citation events.  Each entry uses the
    1-based position in ``page_ref_ids`` as ``citation_id`` (matching
    what the speech LLM is told to use).
    """
    result: list[SpeechCitation] = []
    for local_idx, global_ref_idx in enumerate(page_ref_ids):
        list_idx = global_ref_idx - 1
        if list_idx < 0 or list_idx >= len(reference_list):
            continue
        _, _, file_path, file_uuid, chunk_index = reference_list[list_idx]
        result.append(SpeechCitation(
            action="open",
            citation_id=local_idx + 1,  # 1-based local ID
            char_offset=0,              # placeholder
            reference_idx=global_ref_idx,
            file_path=file_path or "",
            file_uuid=file_uuid,
            chunk_index=chunk_index,
        ))
    return result


def _resolve_reference(
    local_citation_id: int,
    page_ref_ids: List[int],
    reference_list: list,
) -> tuple[Optional[int], Optional[str]]:
    """Map a per-page local citation_id to a global reference index and file path.

    Returns (global_reference_idx_or_None, file_path_or_None).
    """
    if page_ref_ids:
        # Preferred path: outline assigned reference_ids to this page.
        # local_citation_id is 1-based index into page_ref_ids.
        local_idx = local_citation_id - 1
        if local_idx < 0 or local_idx >= len(page_ref_ids):
            return None, None
        global_ref_idx = page_ref_ids[local_idx]  # 1-based global index
    else:
        # Fallback: outline didn't assign reference_ids for this page.
        # Treat local_citation_id as a direct 1-based index into reference_list.
        global_ref_idx = local_citation_id

    list_idx = global_ref_idx - 1
    if list_idx < 0 or list_idx >= len(reference_list):
        return None, None
    _, _, file_path, _, _ = reference_list[list_idx]
    return global_ref_idx, file_path or ""


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
You are sitting beside a student, both looking at the same slide. The student can already \
read what is on the page — your job is to WALK THEM THROUGH it: explain, clarify, connect \
ideas, and add depth.

Generate ONLY what you would say aloud — natural, conversational, like a real tutor \
explaining a slide in office hours.

### YOUR ROLE:
- You are narrating the page the student sees on their screen. Do not restate bullet \
points verbatim — paraphrase, unpack, and explain WHY things work.
- Refer to the slide naturally: "Looking at this first point...", "Notice the code \
example here...", "As shown on the slide..."
- Build your explanation around the reference materials. The references are your teaching \
notes — paraphrase their key ideas, walk through their examples, and anchor back to what \
they say. Do not generate a generic explanation and tack on citations as an afterthought.

### FORMATTING — TTS OUTPUT:
- No markdown, no code fences, no bullet lists, no headings.
- No special symbols: avoid parentheses, brackets (except citation markers), asterisks, \
slashes, equals signs, angle brackets, and similar characters that cannot be spoken naturally.
- When the slide contains code, describe what it does in plain words. For example: "Here \
we have a function called make adder that takes a parameter n and returns a new function."
- When the slide contains a formula, explain its meaning verbally instead of reading \
symbols. For example: "This says the running time grows proportionally to the log of n."
- End each sentence with a period.

### PACING AND DEPTH:
- Adapt to the teaching goal. If the goal is basic understanding, explain concepts simply \
and build intuition. If the goal involves applying, analyzing, or evaluating, go deeper \
into reasoning and trade-offs.
- Vary pacing naturally — sometimes slow down for a key insight, sometimes move briskly \
through straightforward points.
- This is one page of a multi-page lesson. Stay focused on this page's content. Do NOT \
repeat what was covered on a previous page.

### CITATIONS — SHOWING REFERENCES ON THE STUDENT'S SCREEN:
When you insert [cite:N], the student's screen opens the referenced file and scrolls to \
the relevant section. When you insert [/cite:N], it closes. Think of citing as saying \
"let me pull up the source so you can see this."

Rules:
- Insert [cite:N] RIGHT BEFORE the sentence where you begin discussing content from that \
reference. Insert [/cite:N] AFTER the last sentence that draws from it.
- Cite when seeing the original material adds value — when you are paraphrasing a specific \
passage, walking through an example from the notes, or when the original notation or \
diagram would help the student follow along.
- Do not force citations. If you are making a general bridging statement or transition, \
no citation is needed.
- If no citations are provided, do not use any markers.
- Example: "Now let me show you what the lecture notes say about this. [cite:2]Binary \
search works by repeatedly dividing the search interval in half, comparing the target to \
the middle element each time.[/cite:2] So each step cuts the problem in half — that is \
where the log n comes from."
"""

INTRO_SPEECH_SYSTEM_PROMPT = """\
You are TAI, a university tutor for {course_code}.
You are about to begin a spoken lesson for a student.
Generate ONLY what you would say — natural, conversational, like a real lecture.

Rules:
- No markdown, no code fences, no bullet lists, no brackets.
- Start by acknowledging the student's question and naturally transition into your answer.
- Keep it concise — this is just the opening, not the full lesson."""


async def generate_speech_script(
    engine: Any,
    course_code: str,
    user_content: str,
    system_prompt: Optional[str] = None,
    temperature: float = 0.7,
    max_tokens: int = 1500,
) -> str:
    """Generate a speech script from the model, returning the full text."""
    from app.services.generation.model_call import is_openai_client
    system = system_prompt or PAGE_SPEECH_SYSTEM_PROMPT.format(course_code=course_code)
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user_content},
    ]
    if is_openai_client(engine):
        # AsyncOpenAI / vLLM client — call chat.completions.create directly
        from app.config import settings
        stream = await engine.chat.completions.create(
            model=settings.vllm_chat_model,
            messages=messages,
            stream=True,
            temperature=temperature,
            max_tokens=max_tokens,
            extra_body={
                "chat_template_kwargs": {"enable_thinking": False},
            },
        )
    else:
        # Callable engine (OpenAIModelClient, RemoteModelClient)
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
            delta = chunk.choices[0].delta
            token = getattr(delta, "content", None)
            # Fallback: use reasoning_content if content is empty
            if not token:
                token = getattr(delta, "reasoning_content", None)
            if token:
                full_text += token
    return full_text


async def generate_intro_speech(
    engine: Any,
    course_code: str,
    student_question: str,
) -> str:
    """
    Generate the intro (page 0) speech that acknowledges the student's
    question and transitions into the lesson.
    """
    user_content = (
        f'The student asked: "{student_question}"\n\n'
        f"Generate a brief spoken intro that acknowledges the student's question "
        f"and naturally transitions into your answer."
    )
    system = INTRO_SPEECH_SYSTEM_PROMPT.format(course_code=course_code)
    return await generate_speech_script(
        engine, course_code, user_content, system_prompt=system,
    )


def _parse_speech_citations(
    raw_speech: str,
    page_citations: list[SpeechCitation],
) -> tuple[str, list[SpeechCitation]]:
    """Parse ``[cite:N]`` / ``[/cite:N]`` markers out of raw speech text.

    Returns (clean_text, speech_citations) where each SpeechCitation has its
    ``char_offset`` set to the position in *clean_text* where the event fires.

    ``page_citations`` provides the metadata (reference_idx, file_path,
    quote_text) keyed by citation_id.
    """
    # Build lookup: citation_id → first "open" SpeechCitation for metadata
    meta: dict[int, SpeechCitation] = {}
    for sc in page_citations:
        if sc.action == "open" and sc.citation_id not in meta:
            meta[sc.citation_id] = sc

    result_citations: list[SpeechCitation] = []
    clean = ""
    pos = 0

    marker_re = re.compile(r'\[(/?)cite:(\d+)\]')

    for m in marker_re.finditer(raw_speech):
        # Append text before this marker
        clean += raw_speech[pos:m.start()]
        pos = m.end()

        is_close = m.group(1) == "/"
        cid = int(m.group(2))
        src = meta.get(cid)

        if is_close:
            result_citations.append(SpeechCitation(
                action="close",
                citation_id=cid,
                char_offset=len(clean),
                reference_idx=src.reference_idx if src else None,
                file_uuid=src.file_uuid if src else None,
                chunk_index=src.chunk_index if src else None,
            ))
        else:
            result_citations.append(SpeechCitation(
                action="open",
                citation_id=cid,
                char_offset=len(clean),
                quote_text=src.quote_text if src else None,
                reference_idx=src.reference_idx if src else None,
                file_path=src.file_path if src else None,
                file_uuid=src.file_uuid if src else None,
                chunk_index=src.chunk_index if src else None,
            ))

    # Append remaining text
    clean += raw_speech[pos:]

    # Fallback: if LLM produced no markers, pass through the original
    # page_citations (with char_offset=0) so frontend still knows which
    # references this page uses — it can show them all at page start.
    if not result_citations and page_citations:
        return clean, page_citations

    return clean, result_citations


async def generate_page_speech(
    engine: Any,
    course_code: str,
    page_idx: int,
    page_title: str,
    goal: str,
    page_content: str,
    total_pages: int,
    previous_titles: List[str],
    previous_speech: str = "",
    page_citations: Optional[list[SpeechCitation]] = None,
) -> tuple[str, list[SpeechCitation]]:
    """
    Generate a TTS speech script for a single content page.

    Speech is generated sequentially: each page waits for the previous page's
    speech to complete, and the previous page's speech content is included in
    the prompt to avoid repetition.

    Returns:
        (clean_speech_text, speech_citations) — text with markers stripped,
        and SpeechCitation list with char_offset for frontend synchronization.
    """
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

    # Build citation context for the prompt
    citation_section = ""
    if page_citations:
        open_cites = [c for c in page_citations if c.action == "open"]
        if open_cites:
            lines = []
            for c in open_cites:
                label = f"citation_id={c.citation_id}"
                if c.file_path:
                    label += f", file: {c.file_path}"
                if c.quote_text:
                    label += f', quote: "{c.quote_text}"'
                lines.append(f"  - [{label}]")
            citation_section = (
                "\n--- Available citations for this page ---\n"
                + "\n".join(lines)
                + "\n--- End of citations ---\n"
            )

    user_content = (
        f'Page {page_idx + 1} of {total_pages}: "{page_title}"\n'
        f"Teaching goal: {goal}\n\n"
        f"--- Page content (what the student sees on the slide) ---\n"
        f"{page_content}\n"
        f"--- End of page content ---\n\n"
        f"Previous pages covered: {prev_pages}\n"
        f"{prev_speech_section}"
        f"{citation_section}\n"
        f"Generate what you would say aloud to explain this page's content to the student. "
        f"Do not repeat what was already said on the previous page."
    )
    raw_speech = await generate_speech_script(engine, course_code, user_content)
    return _parse_speech_citations(raw_speech, page_citations or [])


async def stream_page_speech(
    engine: Any,
    course_code: str,
    page_index: int,
    page_idx: int,
    page_title: str,
    goal: str,
    page_content: str,
    total_pages: int,
    previous_titles: List[str],
    previous_speech: str = "",
    page_citations: Optional[list[SpeechCitation]] = None,
) -> AsyncIterator[str]:
    """
    Streaming version of generate_page_speech.

    Yields SSE events as the speech LLM generates tokens:
      - ``page.speech.delta`` — sentence-level clean text chunks
      - ``response.citation.open`` / ``response.citation.close`` — inline citation events
      - ``page.speech.done`` — final event with full text + all citations with char_offset

    The ``last_speech_text`` for the next page can be obtained from the
    ``page.speech.done`` event's ``full_text`` field.
    """
    from app.services.generation.model_call import is_openai_client

    # --- Build user_content (same as generate_page_speech) ---
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
    citation_section = ""
    if page_citations:
        open_cites = [c for c in page_citations if c.action == "open"]
        if open_cites:
            lines = []
            for c in open_cites:
                label = f"citation_id={c.citation_id}"
                if c.file_path:
                    label += f", file: {c.file_path}"
                if c.quote_text:
                    label += f', quote: "{c.quote_text}"'
                lines.append(f"  - [{label}]")
            citation_section = (
                "\n--- Available citations for this page ---\n"
                + "\n".join(lines)
                + "\n--- End of citations ---\n"
            )
    user_content = (
        f'Page {page_idx + 1} of {total_pages}: "{page_title}"\n'
        f"Teaching goal: {goal}\n\n"
        f"--- Page content (what the student sees on the slide) ---\n"
        f"{page_content}\n"
        f"--- End of page content ---\n\n"
        f"Previous pages covered: {prev_pages}\n"
        f"{prev_speech_section}"
        f"{citation_section}\n"
        f"Generate what you would say aloud to explain this page's content to the student. "
        f"Do not repeat what was already said on the previous page."
    )

    # --- Build citation metadata lookup ---
    meta: dict[int, SpeechCitation] = {}
    for sc in (page_citations or []):
        if sc.action == "open" and sc.citation_id not in meta:
            meta[sc.citation_id] = sc

    marker_re = re.compile(r'\[(/?)cite:(\d+)\]')

    # --- Stream tokens from speech LLM ---
    system = PAGE_SPEECH_SYSTEM_PROMPT.format(course_code=course_code)
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user_content},
    ]
    if is_openai_client(engine):
        from app.config import settings
        llm_stream = await engine.chat.completions.create(
            model=settings.vllm_chat_model,
            messages=messages,
            stream=True,
            temperature=0.7,
            max_tokens=1500,
            extra_body={"chat_template_kwargs": {"enable_thinking": False}},
        )
    else:
        llm_stream = await engine(
            user_content, messages=messages,
            stream=True, temperature=0.7, max_tokens=1500,
        )

    # --- Accumulate tokens, flush on sentence boundaries ---
    raw_buffer = ""        # raw tokens (may contain [cite:N] markers)
    total_clean = ""       # all emitted clean text so far
    all_citations: list[SpeechCitation] = []
    seq = 0

    def _flush_sentence(raw_sentence: str):
        """Strip markers from a sentence, yield delta + citation events.

        Returns list of SSE strings to yield and the clean text of this sentence.
        """
        nonlocal total_clean, seq
        events: list[str] = []
        clean = ""
        pos = 0

        for m in marker_re.finditer(raw_sentence):
            clean += raw_sentence[pos:m.start()]
            pos = m.end()

            is_close = m.group(1) == "/"
            cid = int(m.group(2))
            src = meta.get(cid)
            char_off = len(total_clean) + len(clean)

            if is_close:
                sc = SpeechCitation(
                    action="close", citation_id=cid, char_offset=char_off,
                    reference_idx=src.reference_idx if src else None,
                    file_uuid=src.file_uuid if src else None,
                    chunk_index=src.chunk_index if src else None,
                )
                all_citations.append(sc)
                events.append(sse(CitationClose(
                    citation_id=cid, page_index=page_index,
                    reference_idx=src.reference_idx if src else None,
                )))
            else:
                sc = SpeechCitation(
                    action="open", citation_id=cid, char_offset=char_off,
                    quote_text=src.quote_text if src else None,
                    reference_idx=src.reference_idx if src else None,
                    file_path=src.file_path if src else None,
                    file_uuid=src.file_uuid if src else None,
                    chunk_index=src.chunk_index if src else None,
                )
                all_citations.append(sc)
                events.append(sse(CitationOpen(
                    citation_id=cid, page_index=page_index,
                    quote_text=src.quote_text if src else None,
                    reference_idx=src.reference_idx if src else None,
                    file_path=src.file_path if src else None,
                )))

        clean += raw_sentence[pos:]

        if clean.strip():
            events.append(sse(PageSpeechDelta(
                page_index=page_index, seq=seq, text=clean,
            )))
            seq += 1

        total_clean += clean
        return events

    async for chunk in llm_stream:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        token = getattr(delta, "content", None)
        if not token:
            token = getattr(delta, "reasoning_content", None)
        if not token:
            continue

        raw_buffer += token

        # Flush complete sentences (split on ". " boundaries)
        while ". " in raw_buffer:
            sentence_end = raw_buffer.index(". ") + 2  # include ". "
            sentence = raw_buffer[:sentence_end]
            raw_buffer = raw_buffer[sentence_end:]
            for evt in _flush_sentence(sentence):
                yield evt

    # Flush remaining buffer
    if raw_buffer.strip():
        for evt in _flush_sentence(raw_buffer):
            yield evt

    # Fallback: if LLM produced no markers, use page_citations as-is
    final_citations = all_citations if all_citations else (page_citations or [])

    # Emit done event with full text + all citations
    yield sse(PageSpeechDone(
        page_index=page_index,
        full_text=total_clean,
        citations=final_citations,
    ))
