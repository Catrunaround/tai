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
from app.services.generation.tutor.generate_pages import run_generate_pages_pipeline

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
    speech_engine = local_engine if USE_LOCAL_SPEECH else openai_engine

    params = GeneratePagesParams(
        course_code=course_code,
        messages=[Message(role="user", content=question)],
        stream=True,
    )

    # Run pipeline — speech generation is now fully handled inside the pipeline
    async for event_str in run_generate_pages_pipeline(
        params, openai_engine, local_engine, speech_engine=speech_engine,
    ):
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
                print(f"  [{ref['reference_idx']}] {ref.get('file_path', 'N/A')} (uuid: {ref.get('file_uuid', 'N/A')})")

        elif evt_type == "outline.complete":
            outline_obj = evt["outline"].get("outline", {})
            all_pages = outline_obj.get("pages", [])
            topic = outline_obj.get("topic", "Untitled")
            print(f"\n--- OUTLINE (Page 0): {topic} ---")
            for i, p in enumerate(all_pages):
                ref_ids = p.get("reference_ids", [])
                print(f"  Page {i+1}: {p['title']}  [reference_ids: {ref_ids}]")

        elif evt_type == "page.open":
            print(f"\n{'='*60}")
            print(f"PAGE {evt['page_index']}: {evt['point']}")
            print(f"{'='*60}")

        elif evt_type == "page.close":
            print(f"\n--- Page {evt['page_index']} content complete ---")

        elif evt_type == "block.open":
            if evt.get("block_type") == "not_readable":
                print("\n  [Code/Formula block]")

        elif evt_type == "block.close":
            pass  # visual separator already handled by block.open

        elif evt_type == "page.speech":
            # Legacy buffered speech event (intro still uses this)
            label = "Intro" if evt["page_index"] == 0 else f"Page {evt['page_index']}"
            print(f"\n--- SPEECH ({label}) ---")
            print(evt["speech_text"])
            print("---")

        elif evt_type == "page.speech.delta":
            label = "Intro" if evt["page_index"] == 0 else f"Page {evt['page_index']}"
            if evt.get("seq", 0) == 0:
                print(f"\n--- SPEECH STREAM ({label}) ---")
            print(evt["text"], end="", flush=True)

        elif evt_type == "page.speech.done":
            label = "Intro" if evt["page_index"] == 0 else f"Page {evt['page_index']}"
            citations = evt.get("citations", [])
            has_offsets = any(c.get("char_offset", 0) > 0 for c in citations)
            if citations and has_offsets:
                print(f"\n  ✅ {len(citations)} citations with char_offset")
                for c in citations:
                    if c["action"] == "open":
                        ref = c.get("reference_idx", "?")
                        fp = c.get("file_path", "")
                        chunk = c.get("chunk_index")
                        chunk_str = f" chunk:{chunk}" if chunk is not None else ""
                        off = c.get("char_offset", 0)
                        print(f"    @{off} [open ref:{ref} {fp}{chunk_str}]")
                    else:
                        off = c.get("char_offset", 0)
                        print(f"    @{off} [close ref:{c.get('reference_idx', '?')}]")
            elif citations:
                print(f"\n  ⚠️  {len(citations)} citations (fallback, no char_offset)")
            print(f"--- END SPEECH ({label}) ---")

        elif evt_type == "page.delta":
            if evt.get("text"):
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
