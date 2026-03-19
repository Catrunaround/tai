"""
Quick test script for the generate-pages pipeline.
Run from the ai_chatbot_backend directory:

    python test_generate_pages.py "YOUR_COURSE_CODE" "Your question here"

Example:
    python test_generate_pages.py CS170 "Explain binary search trees"
"""
import asyncio
import json
import sys

from app.dependencies.model import get_engine_for_mode
from app.core.models.chat_completion import GeneratePagesParams, Message
from app.services.generation.tutor.generate_pages import (
    run_generate_pages_pipeline,
    generate_intro_speech,
    generate_page_speech,
)

# Toggle to use local vLLM for speech generation instead of OpenAI
USE_LOCAL_SPEECH = False


async def main(course_code: str, question: str):
    print(f"\n{'='*60}")
    print(f"Course: {course_code}")
    print(f"Question: {question}")
    print(f"{'='*60}\n")

    # Get engines
    openai_engine = get_engine_for_mode("openai")
    local_engine = get_engine_for_mode("local")

    params = GeneratePagesParams(
        course_code=course_code,
        messages=[Message(role="user", content=question)],
        stream=True,
    )

    # State tracking
    outline_data = None       # Set when outline.complete arrives (may have empty bullets)
    outline_titles = []       # Page titles from outline["outline"] array
    page_purposes = {}        # {page_idx: purpose} from page.start events
    total_pages = 0
    current_page_idx = -1
    current_page_title = ""

    # Sequential speech tracking — each page waits for the previous page's speech
    last_speech_text = ""     # Speech generated for the previous page
    # Buffer page speech data until outline arrives (so Intro speech goes first)
    buffered_page_speeches = []  # [(page_idx, page_title, sub_bullets), ...]

    async def _generate_page_speech_sequential(page_idx, page_title, sub_bullets, use_local=False):
        """Generate speech for a content page sequentially, using previous speech context."""
        nonlocal last_speech_text
        engine = local_engine if use_local else openai_engine
        purpose = page_purposes.get(page_idx, "")
        prev_titles = outline_titles[:page_idx - 1] if page_idx > 1 else []

        speech_text = await generate_page_speech(
            engine=engine,
            course_code=course_code,
            page_idx=page_idx - 1,  # generate_page_speech uses 0-based index
            page_title=page_title,
            purpose=purpose,
            sub_bullets=sub_bullets,
            total_pages=total_pages,
            previous_titles=prev_titles,
            previous_speech=last_speech_text,
        )
        print(f"\n--- SPEECH (Page {page_idx}) ---")
        print(speech_text)
        print("---")
        last_speech_text = speech_text
        return speech_text

    # Run pipeline and print each SSE event
    async for event_str in run_generate_pages_pipeline(params, openai_engine, local_engine):
        # Parse the SSE data line
        if not event_str.startswith("data: "):
            continue
        raw = event_str[len("data: "):].strip()
        if raw == "[DONE]":
            print("\n[DONE]")
            break

        evt = json.loads(raw)
        evt_type = evt.get("type", "")

        if evt_type == "response.reference":
            print(f"\n--- REFERENCES ({len(evt['references'])} found) ---")
            for ref in evt["references"]:
                print(f"  [{ref['reference_idx']}] {ref.get('file_path', 'N/A')}")

        elif evt_type == "outline.complete":
            outline = evt["outline"]
            outline_data = outline
            outline_obj = outline.get("outline", {})
            inferred_depth = outline.get("inferred_depth", "standard")
            # Extract page titles in order (pages array = content pages 1+)
            all_pages = outline_obj.get("pages", [])
            outline_titles = [n["title"] for n in all_pages]
            total_pages = len(outline_titles)
            is_single_page = inferred_depth == "minimal"

            if is_single_page:
                # Single-page: no outline display, no intro speech
                # Just replay any buffered page speeches directly (sequentially)
                for (buf_idx, buf_title, buf_bullets) in buffered_page_speeches:
                    await _generate_page_speech_sequential(buf_idx, buf_title, buf_bullets, use_local=USE_LOCAL_SPEECH)
                buffered_page_speeches = []
            else:
                # Multi-page: show outline + generate intro speech from user question
                topic = outline_obj.get("topic", "Untitled")
                print(f"\n--- OUTLINE (Page 0): {topic} [depth={inferred_depth}] ---")
                for i, title in enumerate(outline_titles):
                    print(f"  Page {i+1}: {title}")

                intro_engine = local_engine if USE_LOCAL_SPEECH else openai_engine
                intro_text = await generate_intro_speech(
                    engine=intro_engine,
                    course_code=course_code,
                    student_question=question,
                    topic=topic,
                    total_pages=total_pages,
                    page_titles=outline_titles,
                )
                print(f"\n--- SPEECH (Intro) ---")
                print(intro_text)
                print("---")
                # Intro speech becomes the "previous speech" for page 1
                last_speech_text = intro_text

                # Now generate buffered page speeches sequentially
                for (buf_idx, buf_title, buf_bullets) in buffered_page_speeches:
                    await _generate_page_speech_sequential(buf_idx, buf_title, buf_bullets, use_local=USE_LOCAL_SPEECH)
                buffered_page_speeches = []

        elif evt_type == "page.start":
            current_page_idx = evt["page_index"]
            current_page_title = evt["point"]
            page_purposes[current_page_idx] = evt.get("purpose", "")
            print(f"\n{'='*60}")
            print(f"PAGE {current_page_idx}: {current_page_title}")
            print(f"{'='*60}")

        elif evt_type == "page.bullets":
            sub_bullets = evt.get("sub_bullets", [])
            print(f"\n  Bullet points:")
            for j, sb in enumerate(sub_bullets):
                if isinstance(sb, dict):
                    print(f"    {j+1}. {sb.get('point', sb)}")
                else:
                    print(f"    {j+1}. {sb}")
            print()

            # Generate speech — buffer if outline not yet available
            if outline_data is None:
                buffered_page_speeches.append(
                    (current_page_idx, current_page_title, sub_bullets)
                )
            else:
                await _generate_page_speech_sequential(current_page_idx, current_page_title, sub_bullets, use_local=USE_LOCAL_SPEECH)

        elif evt_type == "page.block_type":
            if evt.get("block_type") == "not_readable":
                print("\n  [Code/Formula block]")

        elif evt_type == "response.citation.open":
            cid = evt.get("citation_id", "?")
            quote = evt.get("quote_text")
            if quote:
                print(f"\n  [ref:{cid}] \"{quote}\"")
            else:
                print(f"\n  [ref:{cid}]")

        elif evt_type == "response.citation.close":
            pass

        elif evt_type == "page.delta":
            print(evt["text"], end="", flush=True)

        elif evt_type == "page.error":
            print(f"\n[ERROR] Page {evt['page_index']}: {evt['error']}")

        elif evt_type == "done":
            print("\n--- ALL DONE ---")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python test_generate_pages.py <course_code> <question>")
        print('Example: python test_generate_pages.py CS170 "Explain binary search trees"')
        sys.exit(1)

    course_code = sys.argv[1]
    question = " ".join(sys.argv[2:])
    asyncio.run(main(course_code, question))
