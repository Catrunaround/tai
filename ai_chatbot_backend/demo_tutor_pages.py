"""
Interactive demo for the TAI Tutor Pages pipeline.

Runs the full generate-pages pipeline, collects all pages + speech scripts,
calls TTS to generate audio for each page, then opens a self-contained HTML
demo in the browser.

Usage:
    python demo_tutor_pages.py "CS 61A" "Explain recursion"
    python demo_tutor_pages.py "CS 170" "What is dynamic programming?"

Requirements:
    - Backend .env configured with OpenAI key, vLLM URLs
    - Remote vLLM TTS server accessible
"""
import asyncio
import base64
import io
import json
import re
import struct
import sys
import time
import webbrowser
import tempfile
import os

from app.dependencies.model import get_engine_for_mode
from app.core.models.chat_completion import GeneratePagesParams, Message
from app.services.generation.tutor.generate_pages import run_generate_pages_pipeline
from app.services.audio.tts import audio_generator, format_audio_text_message, get_speaker_name
from app.services.generation.prompts.slide_theme import SLIDE_THEME_CSS


# ── TTS helper ──────────────────────────────────────────────────────

async def generate_tts_audio(text: str, course_code: str) -> str:
    """Call TTS for a speech script, return base64-encoded WAV."""
    if not text or not text.strip():
        return ""

    speaker_name = get_speaker_name(course_code)
    audio_message = format_audio_text_message(text)

    # Collect all PCM chunks from TTS stream
    pcm_chunks = []
    try:
        async for chunk_b64 in audio_generator(audio_message, stream=True, speaker_name=speaker_name):
            if chunk_b64:
                pcm_chunks.append(base64.b64decode(chunk_b64))
    except Exception as e:
        print(f"  [TTS ERROR] {e}")
        return ""

    if not pcm_chunks:
        return ""

    # Concatenate PCM and wrap in WAV header
    pcm_data = b"".join(pcm_chunks)
    wav_data = _pcm_to_wav(pcm_data, sample_rate=24000, channels=1, bits_per_sample=16)
    return base64.b64encode(wav_data).decode("utf-8")


def _pcm_to_wav(pcm: bytes, sample_rate: int, channels: int, bits_per_sample: int) -> bytes:
    """Add WAV header to raw PCM data."""
    data_size = len(pcm)
    byte_rate = sample_rate * channels * bits_per_sample // 8
    block_align = channels * bits_per_sample // 8

    buf = io.BytesIO()
    buf.write(b"RIFF")
    buf.write(struct.pack("<I", 36 + data_size))
    buf.write(b"WAVE")
    buf.write(b"fmt ")
    buf.write(struct.pack("<I", 16))
    buf.write(struct.pack("<H", 1))
    buf.write(struct.pack("<H", channels))
    buf.write(struct.pack("<I", sample_rate))
    buf.write(struct.pack("<I", byte_rate))
    buf.write(struct.pack("<H", block_align))
    buf.write(struct.pack("<H", bits_per_sample))
    buf.write(b"data")
    buf.write(struct.pack("<I", data_size))
    buf.write(pcm)
    return buf.getvalue()


# ── Content cleaning ────────────────────────────────────────────────

def clean_block_content(raw: str) -> str:
    """
    Extract markdown_content from raw block data if it looks like
    YAML-style block format (- type: readable ...). Otherwise return as-is.
    """
    if not raw:
        return ""

    # Check if content looks like block data
    if not re.search(r'- type:\s*(readable|not_readable)', raw):
        return raw

    # Extract all markdown_content fields
    parts = []
    for match in re.finditer(r'markdown_content:\s*(.*?)(?=\n- type:|\Z)', raw, re.DOTALL):
        content = match.group(1).strip()
        if content:
            parts.append(content)

    return "\n\n".join(parts) if parts else raw


# ── Pipeline runner ─────────────────────────────────────────────────

async def run_pipeline(course_code: str, question: str, render_mode: str = "json"):
    """Run generate-pages pipeline and collect structured data."""
    openai_engine = get_engine_for_mode("openai")
    local_engine = get_engine_for_mode("local")

    params = GeneratePagesParams(
        course_code=course_code,
        messages=[Message(role="user", content=question)],
        stream=True,
    )

    # Data collectors
    references = []
    outline = None
    pages = {}       # page_idx -> {title, goal, content, speech_text, citations, blocks}
    intro_speech = ""
    # Backup: collect page info from page.open events in case outline.complete has empty pages
    page_open_info = []  # [{title, goal}, ...]
    # Track current block for visual hints
    current_block = {}  # page_idx -> {block_type, layout, visual_emphasis, icon_hint, content}

    print(f"\n{'='*60}")
    print(f"  TAI Tutor Pages Demo")
    print(f"  Course: {course_code}")
    print(f"  Question: {question}")
    print(f"{'='*60}\n")

    t0 = time.time()
    print("[1/3] Running generate-pages pipeline...")

    async for event_str in run_generate_pages_pipeline(
        params, openai_engine, local_engine, speech_engine=openai_engine,
        use_openai_pages=True, render_mode=render_mode,
    ):
        if not event_str.startswith("data: "):
            continue
        raw = event_str[len("data: "):].strip()
        if raw == "[DONE]":
            break

        evt = json.loads(raw)
        evt_type = evt.get("type", "")

        if evt_type == "response.reference":
            references = evt["references"]
            print(f"  References: {len(references)} found")

        elif evt_type == "page.speech":
            # Intro speech (page 0)
            intro_speech = evt.get("speech_text", "")
            print(f"  Intro speech: {len(intro_speech)} chars")

        elif evt_type == "outline.complete":
            outline = evt.get("outline", {}).get("outline", {})
            n_pages = len(outline.get("pages", []))
            print(f"  Outline: \"{outline.get('topic', '')}\" ({n_pages} pages)")

        elif evt_type == "page.open":
            idx = evt["page_index"]
            title = evt.get("point", f"Page {idx}")
            goal = evt.get("goal", "")
            pages[idx] = {
                "title": title,
                "goal": goal,
                "content": "",
                "speech_text": "",
                "citations": [],
                "blocks": [],
            }
            page_open_info.append({"title": title, "goal": goal})
            print(f"  Page {idx}: \"{title}\" generating...", end="", flush=True)

        elif evt_type == "block.open":
            idx = evt["page_index"]
            current_block[idx] = {
                "block_type": evt.get("block_type", "readable"),
                "layout": evt.get("layout", "default"),
                "visual_emphasis": evt.get("visual_emphasis", "primary"),
                "icon_hint": evt.get("icon_hint"),
                "content": "",
            }

        elif evt_type == "page.delta":
            idx = evt["page_index"]
            text = evt.get("text", "")
            if idx in pages:
                pages[idx]["content"] += text
            if idx in current_block:
                current_block[idx]["content"] += text

        elif evt_type == "block.close":
            idx = evt["page_index"]
            if idx in current_block and idx in pages:
                pages[idx]["blocks"].append(dict(current_block[idx]))
                del current_block[idx]

        elif evt_type == "page.close":
            idx = evt["page_index"]
            # Flush any unclosed block
            if idx in current_block and idx in pages:
                pages[idx]["blocks"].append(dict(current_block[idx]))
                del current_block[idx]
            if idx in pages:
                n = len(pages[idx]["content"])
                print(f" {n} chars")

        elif evt_type == "page.speech.delta":
            idx = evt["page_index"]
            if idx in pages:
                pages[idx]["speech_text"] += evt.get("text", "")

        elif evt_type == "page.speech.done":
            idx = evt["page_index"]
            full = evt.get("full_text", "")
            if idx in pages and full:
                pages[idx]["speech_text"] = full
            citations = evt.get("citations", [])
            if idx in pages:
                pages[idx]["citations"] = citations
            print(f"  Page {idx} speech: {len(pages.get(idx, {}).get('speech_text', ''))} chars")

    pipeline_time = time.time() - t0
    print(f"\n  Pipeline completed in {pipeline_time:.1f}s")

    # Fix: if outline pages are empty, use page_open_info as fallback
    if outline:
        outline_pages = outline.get("pages", [])
        if not outline_pages and page_open_info:
            outline["pages"] = page_open_info

    # ── Generate TTS audio ──────────────────────────────────────────
    print(f"\n[2/3] Generating TTS audio...")

    audio_data = {}  # page_idx -> base64 wav (0 = intro)

    # Intro speech TTS
    if intro_speech:
        print(f"  Generating intro audio...", end="", flush=True)
        audio_data[0] = await generate_tts_audio(intro_speech, course_code)
        if audio_data[0]:
            print(f" done")
        else:
            print(f" failed")

    # Page speech TTS
    for idx in sorted(pages.keys()):
        speech = pages[idx].get("speech_text", "")
        if speech:
            print(f"  Generating page {idx} audio...", end="", flush=True)
            audio_data[idx] = await generate_tts_audio(speech, course_code)
            if audio_data[idx]:
                print(f" done")
            else:
                print(f" failed")

    # ── Generate HTML ───────────────────────────────────────────────
    print(f"\n[3/3] Generating HTML demo...")

    html = build_html(
        course_code=course_code,
        question=question,
        outline=outline,
        intro_speech=intro_speech,
        pages=pages,
        references=references,
        audio_data=audio_data,
        render_mode=render_mode,
    )

    # Write to temp file and open
    fd, path = tempfile.mkstemp(suffix=".html", prefix="tai_demo_")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"  HTML written to: {path}")
    print(f"  Opening in browser...\n")
    webbrowser.open(f"file://{path}")

    return path


# ── HTML builder ────────────────────────────────────────────────────

def _esc(s):
    """Escape HTML special characters."""
    if not s:
        return ""
    return (s.replace("&", "&amp;").replace("<", "&lt;")
             .replace(">", "&gt;").replace('"', "&quot;"))


_ICON_SVGS = {
    "lightbulb": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" width="20" height="20"><path d="M15 14c.2-1 .7-1.7 1.5-2.5 1-.9 1.5-2.2 1.5-3.5A6 6 0 0 0 6 8c0 1 .2 2.2 1.5 3.5.7.7 1.3 1.5 1.5 2.5"/><path d="M9 18h6"/><path d="M10 22h4"/></svg>',
    "warning": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" width="20" height="20"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><path d="M12 9v4"/><path d="M12 17h.01"/></svg>',
    "code": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" width="20" height="20"><polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/></svg>',
    "formula": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" width="20" height="20"><path d="M4 20h4l6-14h4"/><path d="M6 12h8"/></svg>',
    "check": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" width="20" height="20"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>',
    "question": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" width="20" height="20"><circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/><path d="M12 17h.01"/></svg>',
}


def _esc_script(s):
    """Escape content for safe embedding inside <script> tags.
    Only need to escape </script> sequences — everything else is safe.
    """
    if not s:
        return ""
    return s.replace("</script>", "<\\/script>")


def _render_blocks_html(blocks):
    """Render blocks with visual layout hints as styled HTML.

    Markdown content is stored in <script type="text/x-markdown"> tags to avoid
    browser HTML parsing (e.g. `<` in code being treated as a tag). The JS
    renderer reads from these script tags and renders via marked.js.
    """
    parts = []
    step_counter = 0

    for block in blocks:
        layout = block.get("layout", "default")
        emphasis = block.get("visual_emphasis", "primary")
        icon_hint = block.get("icon_hint")
        content = _esc_script(block.get("content", ""))
        block_type = block.get("block_type", "readable")

        icon_html = ""
        if icon_hint and icon_hint in _ICON_SVGS:
            icon_html = f'<span class="block-icon">{_ICON_SVGS[icon_hint]}</span>'

        # Markdown source in a script tag (not parsed by browser), rendered div beside it
        md_pair = f'<script type="text/x-markdown">{content}</script><div class="markdown-content"></div>'

        emphasis_class = f"emphasis-{emphasis}"

        if block_type == "not_readable":
            parts.append(f'<div class="slide-block block-code {emphasis_class}">{md_pair}</div>')
            continue

        if layout == "centered":
            parts.append(f'<div class="slide-block block-centered {emphasis_class}">{icon_html}{md_pair}</div>')
        elif layout == "highlight-box":
            box_class = "block-highlight-accent" if emphasis == "accent" else "block-highlight"
            parts.append(f'<div class="slide-block {box_class}"><div class="block-row">{icon_html}{md_pair}</div></div>')
        elif layout == "definition":
            parts.append(f'<div class="slide-block block-definition"><div class="block-row">{icon_html}{md_pair}</div></div>')
        elif layout == "comparison":
            parts.append(f'<div class="slide-block block-comparison {emphasis_class}">{icon_html}{md_pair}</div>')
        elif layout == "steps":
            step_counter += 1
            parts.append(f'<div class="slide-block block-steps"><span class="step-number">{step_counter}</span>{md_pair}</div>')
        else:
            # default
            parts.append(f'<div class="slide-block block-default {emphasis_class}"><div class="block-row">{icon_html}{md_pair}</div></div>')

    return "\n".join(parts)


def _esc_attr(s):
    """Escape for safe use inside HTML attribute values (srcdoc)."""
    if not s:
        return ""
    return (s.replace("&", "&amp;").replace('"', "&quot;")
             .replace("<", "&lt;").replace(">", "&gt;"))


def build_html(course_code, question, outline, intro_speech, pages, references, audio_data, render_mode="json"):
    topic = outline.get("topic", "Untitled") if outline else "Untitled"
    outline_pages = outline.get("pages", []) if outline else []

    # References section (built early so page cards can include it)
    ref_html = ""
    if references:
        ref_items = ""
        for r in references:
            ref_items += f'<li>[{r.get("reference_idx", "")}] {_esc(r.get("file_path", "N/A"))}</li>'
        ref_html = f'<div class="references"><h3>References</h3><ul>{ref_items}</ul></div>'

    # Build page cards HTML
    page_cards = []
    skip_overview = len(outline_pages) <= 1

    # Intro speech / audio (used by overview or folded into page 1)
    intro_audio_html = ""
    if audio_data.get(0):
        intro_audio_html = f'''
        <div class="audio-player">
            <audio controls><source src="data:audio/wav;base64,{audio_data[0]}" type="audio/wav"></audio>
        </div>'''

    intro_speech_html = ""
    if intro_speech:
        intro_speech_html = f'''<button class="speech-toggle" onclick="toggleSpeech(this)">&#x25B8; Show narration</button>
            <div class="speech-section"><h3>Intro Narration</h3><p class="speech-text">{_esc(intro_speech)}</p>{intro_audio_html}</div>'''

    # Page 0: Outline / Intro — skip when there's only one content page
    if not skip_overview:
        outline_items = ""
        for i, p in enumerate(outline_pages):
            title = p.get("title", "")
            goal = p.get("goal", "")
            outline_items += f'''<li>
                <strong>{_esc(title)}</strong>
                {f'<br><span class="goal-text">{_esc(goal)}</span>' if goal else ''}
            </li>'''

        page_cards.append(f'''
    <div class="page-card active" id="page-0">
        <div class="page-title-bar">
            <h2>{_esc(topic)}</h2>
            <div class="goal">Lesson Overview</div>
        </div>
        <div class="page-body">
            <div class="outline-list">
                <h3>Lesson Outline</h3>
                <ol>{outline_items}</ol>
            </div>
            {intro_speech_html}
        </div>
    </div>''')

    # Pages 1+
    for idx in sorted(pages.keys()):
        p = pages[idx]
        audio_html = ""
        if audio_data.get(idx):
            audio_html = f'''
            <div class="audio-player">
                <audio controls><source src="data:audio/wav;base64,{audio_data[idx]}" type="audio/wav"></audio>
            </div>'''

        # Render page content based on mode
        if render_mode == "explore":
            # Explore mode: wrap AI body HTML in fixed CSS/JS framework
            from app.services.generation.prompts.explore_slide_system import EXPLORE_BASE_CSS, EXPLORE_BASE_JS
            raw_html = p.get("content", "")
            if raw_html.strip():
                resize_script = '<script>function _r(){parent.postMessage({type:"resize",height:document.documentElement.scrollHeight},"*")}window.addEventListener("load",_r);new ResizeObserver(_r).observe(document.body);</script>'
                iframe_html = f'<!DOCTYPE html><html><head><link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet"><style>{EXPLORE_BASE_CSS}</style></head><body>{raw_html}<script>{EXPLORE_BASE_JS}</script>{resize_script}</body></html>'
                content_html = f'<iframe srcdoc="{_esc_attr(iframe_html)}" scrolling="no" class="slide-iframe"></iframe>'
            else:
                content_html = '<em>No content generated</em>'
        elif render_mode == "interactive":
            # Interactive mode: seamless iframe with auto-height
            raw_html = p.get("content", "")
            if raw_html.strip():
                # Inject height-reporting script into the HTML doc
                resize_script = '<script>function _r(){parent.postMessage({type:"resize",height:document.documentElement.scrollHeight},"*")}window.addEventListener("load",_r);new ResizeObserver(_r).observe(document.body);</script>'
                # Insert resize script before </body> or append
                if '</body>' in raw_html:
                    iframe_html = raw_html.replace('</body>', resize_script + '</body>')
                else:
                    iframe_html = raw_html + resize_script
                content_html = f'<iframe srcdoc="{_esc_attr(iframe_html)}" scrolling="no" class="slide-iframe"></iframe>'
            else:
                content_html = '<em>No content generated</em>'
        elif render_mode == "html":
            # Static HTML artifact mode: inject directly
            raw_html = p.get("content", "")
            if raw_html.strip():
                content_html = f'<div class="slide-content">{raw_html}</div>'
            else:
                content_html = '<em>No content generated</em>'
        else:
            # JSON block mode: render blocks with visual layout hints
            blocks = p.get("blocks", [])
            if blocks:
                content_html = f'<div class="blocks-container">{_render_blocks_html(blocks)}</div>'
            else:
                cleaned_content = clean_block_content(p["content"]) if p["content"] else ""
                content_html = f'<div class="content-section markdown-content">{_esc(cleaned_content) if cleaned_content else "<em>No content generated</em>"}</div>'

        speech_html = ""
        if p.get("speech_text"):
            speech_html = f'''<button class="speech-toggle" onclick="toggleSpeech(this)">&#x25B8; Show narration</button>
            <div class="speech-section"><h3>Narration Script</h3><p class="speech-text">{_esc(p["speech_text"])}</p>{audio_html}</div>'''

        # When overview is skipped, page 1 is the default active page
        # and gets the intro speech prepended
        is_first = (idx == sorted(pages.keys())[0])
        active_cls = " active" if (skip_overview and is_first) else ""
        extra_speech = intro_speech_html if (skip_overview and is_first) else ""

        page_cards.append(f'''
    <div class="page-card{active_cls}" id="page-{idx}">
        <div class="page-title-bar">
            <h2>{_esc(p["title"])}</h2>
            {f'<div class="goal">{_esc(p["goal"])}</div>' if p.get("goal") else ''}
        </div>
        <div class="page-body">
            {extra_speech}
            {content_html}
            {speech_html}
            {ref_html if idx == sorted(pages.keys())[-1] else ''}
        </div>
    </div>''')

    # Build nav dots
    if skip_overview:
        nav_items = []
        first_page = sorted(pages.keys())[0] if pages else 1
        for idx in sorted(pages.keys()):
            active = " active" if idx == first_page else ""
            nav_items.append(f'<button class="nav-dot{active}" onclick="goToPage({idx})">Page {idx}</button>')
        page_indices_js = ", ".join([str(i) for i in sorted(pages.keys())])
    else:
        nav_items = ['<button class="nav-dot active" onclick="goToPage(0)">Overview</button>']
        for idx in sorted(pages.keys()):
            nav_items.append(f'<button class="nav-dot" onclick="goToPage({idx})">Page {idx}</button>')
        page_indices_js = ", ".join(["0"] + [str(i) for i in sorted(pages.keys())])

    return f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>TAI Tutor Demo - {_esc(topic)}</title>
<script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0f172a; color: #e2e8f0; min-height: 100vh; }}

/* ── Top bar: compact header + nav ── */
.topbar {{ display: flex; align-items: center; justify-content: space-between; padding: 0.6rem 2rem; background: linear-gradient(135deg, #1e3a5f, #2d1b69); border-bottom: 1px solid #334155; position: sticky; top: 0; z-index: 10; }}
.topbar-left {{ display: flex; align-items: center; gap: 1rem; }}
.topbar-left h1 {{ font-size: 1.1rem; background: linear-gradient(90deg, #60a5fa, #a78bfa); -webkit-background-clip: text; -webkit-text-fill-color: transparent; white-space: nowrap; }}
.topbar-left .question {{ color: #94a3b8; font-size: 0.85rem; font-style: italic; max-width: 400px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
.topbar-nav {{ display: flex; align-items: center; gap: 0.5rem; }}
.nav-dot {{ padding: 0.35rem 0.75rem; border-radius: 9999px; border: 1px solid #475569; background: transparent; color: #94a3b8; cursor: pointer; font-size: 0.8rem; white-space: nowrap; transition: all 0.2s; }}
.nav-dot:hover {{ border-color: #60a5fa; color: #60a5fa; }}
.nav-dot.active {{ background: #3b82f6; color: white; border-color: #3b82f6; }}
.nav-arrow {{ background: none; border: none; color: #94a3b8; cursor: pointer; font-size: 1.2rem; padding: 0.25rem 0.5rem; transition: color 0.2s; }}
.nav-arrow:hover {{ color: #60a5fa; }}
.nav-arrow:disabled {{ opacity: 0.3; cursor: not-allowed; }}

/* ── Main slide area ── */
.slide-area {{ max-width: 1200px; margin: 0 auto; padding: 0 3rem; }}
.page-card {{ display: none; }}
.page-card.active {{ display: block; animation: fadeIn 0.25s ease; }}
@keyframes fadeIn {{ from {{ opacity: 0; }} to {{ opacity: 1; }} }}

/* Page title bar */
.page-title-bar {{ padding: 1.5rem 0 1rem; }}
.page-title-bar h2 {{ font-size: 1.5rem; color: #f1f5f9; }}
.page-title-bar .goal {{ color: #94a3b8; font-size: 0.9rem; margin-top: 0.3rem; }}

/* Slide content: natural flow, scrolls with page */
.page-body {{ padding: 0 0 3rem; }}

/* ── Markdown / content styling ── */
.markdown-content, .content-section {{ line-height: 1.8; color: #cbd5e1; }}
.markdown-content h1, .markdown-content h2, .markdown-content h3, .markdown-content h4,
.content-section h1, .content-section h2, .content-section h3, .content-section h4 {{ color: #f1f5f9; margin: 1em 0 0.5em; }}
.markdown-content h1, .content-section h1 {{ font-size: 1.4rem; }}
.markdown-content h2, .content-section h2 {{ font-size: 1.25rem; }}
.markdown-content h3, .content-section h3 {{ font-size: 1.1rem; }}
.markdown-content strong, .content-section strong {{ color: #f1f5f9; }}
.markdown-content em {{ color: #94a3b8; }}
.markdown-content ul, .markdown-content ol, .content-section ul, .content-section ol {{ padding-left: 1.5rem; margin: 0.6em 0; }}
.markdown-content li, .content-section li {{ margin-bottom: 0.3em; }}
.markdown-content pre, .content-section pre {{ background: #0f172a; border: 1px solid #334155; border-radius: 8px; padding: 1rem; overflow-x: auto; margin: 0.75em 0; }}
.markdown-content code, .content-section code {{ font-family: 'SF Mono', 'Fira Code', 'Cascadia Code', monospace; font-size: 0.9em; }}
.markdown-content :not(pre) > code, .content-section :not(pre) > code {{ background: #334155; padding: 0.15em 0.4em; border-radius: 4px; color: #e2e8f0; }}
.markdown-content blockquote, .content-section blockquote {{ border-left: 3px solid #3b82f6; padding-left: 1rem; margin: 0.75em 0; color: #94a3b8; }}
.markdown-content p, .content-section p {{ margin: 0.5em 0; }}
.markdown-content table {{ width: 100%; border-collapse: collapse; margin: 0.75em 0; }}
.markdown-content th {{ text-align: left; padding: 0.5rem 0.75rem; background: #1e293b; border-bottom: 1px solid #475569; font-weight: 600; color: #f1f5f9; }}
.markdown-content td {{ padding: 0.5rem 0.75rem; border-bottom: 1px solid #334155; }}

/* ── Speech toggle (collapsed by default) ── */
.speech-toggle {{ display: inline-flex; align-items: center; gap: 0.4rem; cursor: pointer; color: #60a5fa; font-size: 0.85rem; padding: 0.5rem 0; margin-top: 0.5rem; border: none; background: none; }}
.speech-toggle:hover {{ color: #93c5fd; }}
.speech-section {{ max-height: 0; overflow: hidden; transition: max-height 0.3s ease; background: #0f172a; border-radius: 8px; }}
.speech-section.open {{ max-height: 2000px; padding: 1.25rem; margin-top: 0.5rem; }}
.speech-section h3 {{ color: #a78bfa; font-size: 0.9rem; margin-bottom: 0.5rem; }}
.speech-text {{ color: #94a3b8; line-height: 1.6; font-size: 0.9rem; white-space: pre-wrap; }}
.audio-player {{ margin-top: 0.75rem; }}
.audio-player audio {{ width: 100%; height: 36px; border-radius: 8px; }}

/* ── Outline list (page 0) ── */
.outline-list ol {{ padding-left: 1.5rem; }}
.outline-list li {{ margin-bottom: 1rem; color: #cbd5e1; line-height: 1.6; }}
.outline-list .goal-text {{ color: #94a3b8; font-size: 0.9rem; font-style: italic; }}
.outline-list h3 {{ color: #60a5fa; margin-bottom: 1rem; }}

/* ── References ── */
.references {{ background: #1e293b; border-radius: 12px; padding: 1.25rem 2rem; border: 1px solid #334155; margin-top: 1rem; }}
.references h3 {{ color: #60a5fa; margin-bottom: 0.5rem; font-size: 0.9rem; }}
.references ul {{ list-style: none; }}
.references li {{ color: #94a3b8; font-size: 0.8rem; padding: 0.2rem 0; font-family: monospace; }}

/* ── Slide blocks ── */
.blocks-container {{ display: flex; flex-direction: column; gap: 0.75rem; }}
.slide-block {{ border-radius: 10px; animation: fadeIn 0.2s ease-out; padding: 1rem 1.25rem; }}
.block-row {{ display: flex; gap: 0.75rem; align-items: flex-start; }}
.block-icon {{ flex-shrink: 0; margin-top: 2px; }}
.emphasis-primary {{ color: #f1f5f9; }}
.emphasis-secondary {{ color: #94a3b8; }}
.emphasis-accent {{ color: #fbbf24; }}
.block-default {{ background: rgba(255,255,255,0.03); }}
.block-centered {{ display: flex; flex-direction: column; align-items: center; text-align: center; padding: 1.5rem 2rem; }}
.block-centered .block-icon {{ margin-bottom: 0.75rem; color: #60a5fa; }}
.block-centered .markdown-content {{ font-size: 1.15rem; font-weight: 500; }}
.block-highlight {{ background: rgba(59,130,246,0.1); border: 1px solid rgba(59,130,246,0.3); }}
.block-highlight .block-icon {{ color: #60a5fa; }}
.block-highlight-accent {{ background: rgba(251,191,36,0.1); border: 1px solid rgba(251,191,36,0.3); }}
.block-highlight-accent .block-icon {{ color: #fbbf24; }}
.block-definition {{ background: rgba(139,92,246,0.05); border-left: 4px solid #8b5cf6; }}
.block-definition .block-icon {{ color: #a78bfa; }}
.block-comparison {{ background: rgba(16,185,129,0.05); border: 1px solid rgba(16,185,129,0.15); }}
.block-comparison .block-icon {{ color: #34d399; }}
.block-steps {{ display: flex; gap: 1rem; align-items: flex-start; padding: 0.75rem 1.25rem; }}
.step-number {{ flex-shrink: 0; display: flex; align-items: center; justify-content: center; width: 2rem; height: 2rem; border-radius: 50%; background: rgba(59,130,246,0.15); border: 1px solid rgba(59,130,246,0.3); color: #60a5fa; font-weight: 700; font-size: 0.9rem; }}
.block-steps + .block-steps {{ margin-top: -0.25rem; padding-top: 0.5rem; }}
.block-code {{ background: #0f172a; border: 1px solid #334155; }}
.block-code .markdown-content code {{ font-family: 'SF Mono', 'Fira Code', monospace; font-size: 0.9em; }}

/* ── Slide content (HTML artifact mode, injected directly) ── */
.slide-content {{ line-height: 1.7; color: #e2e8f0; }}
.slide-content h2 {{ font-size: 1.4rem; color: #f1f5f9; margin: 0 0 0.75rem; }}
.slide-content h3 {{ font-size: 1.15rem; color: #f1f5f9; margin: 0 0 0.5rem; }}
.slide-content h4 {{ font-size: 1rem; color: #f1f5f9; margin: 0 0 0.4rem; }}
.slide-content p {{ margin: 0 0 0.6rem; }}
.slide-content strong {{ color: #f1f5f9; }}
.slide-content em {{ color: #94a3b8; }}
.slide-content a {{ color: #60a5fa; text-decoration: none; }}
.slide-content ul, .slide-content ol {{ padding-left: 1.5rem; margin: 0.5rem 0; }}
.slide-content li {{ margin-bottom: 0.3rem; }}
.slide-content hr {{ border: none; border-top: 1px solid rgba(255,255,255,0.1); margin: 1rem 0; }}
.slide-content .card {{ background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.08); border-radius: 12px; padding: 1.25rem; margin: 0.75rem 0; }}
.slide-content .card-accent {{ background: rgba(59,130,246,0.08); border: 1px solid rgba(59,130,246,0.25); border-left: 4px solid #60a5fa; border-radius: 12px; padding: 1.25rem; margin: 0.75rem 0; }}
.slide-content .card-warning {{ background: rgba(251,191,36,0.08); border: 1px solid rgba(251,191,36,0.25); border-left: 4px solid #fbbf24; border-radius: 12px; padding: 1.25rem; margin: 0.75rem 0; }}
.slide-content .card-success {{ background: rgba(16,185,129,0.08); border: 1px solid rgba(16,185,129,0.2); border-left: 4px solid #34d399; border-radius: 12px; padding: 1.25rem; margin: 0.75rem 0; }}
.slide-content .card-purple {{ background: rgba(139,92,246,0.08); border: 1px solid rgba(139,92,246,0.2); border-left: 4px solid #a78bfa; border-radius: 12px; padding: 1.25rem; margin: 0.75rem 0; }}
.slide-content .text-lg {{ font-size: 1.15rem; }}
.slide-content .text-sm {{ font-size: 0.875rem; }}
.slide-content .text-muted {{ color: #94a3b8; }}
.slide-content .text-highlight {{ color: #60a5fa; }}
.slide-content .text-amber {{ color: #fbbf24; }}
.slide-content .text-green {{ color: #34d399; }}
.slide-content .text-purple {{ color: #a78bfa; }}
.slide-content .font-bold {{ font-weight: 700; }}
.slide-content .font-medium {{ font-weight: 500; }}
.slide-content .font-mono {{ font-family: 'SF Mono', 'Fira Code', monospace; }}
.slide-content .flex {{ display: flex; }}
.slide-content .flex-col {{ flex-direction: column; }}
.slide-content .items-center {{ align-items: center; }}
.slide-content .items-start {{ align-items: flex-start; }}
.slide-content .justify-between {{ justify-content: space-between; }}
.slide-content .gap-2 {{ gap: 0.5rem; }}
.slide-content .gap-3 {{ gap: 0.75rem; }}
.slide-content .gap-4 {{ gap: 1rem; }}
.slide-content .grid-2 {{ display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; }}
.slide-content .mt-2 {{ margin-top: 0.5rem; }}
.slide-content .mt-4 {{ margin-top: 1rem; }}
.slide-content .mb-2 {{ margin-bottom: 0.5rem; }}
.slide-content .mb-4 {{ margin-bottom: 1rem; }}
.slide-content .step {{ display: flex; gap: 1rem; align-items: flex-start; padding: 0.5rem 0; }}
.slide-content .step-num {{ width: 2rem; height: 2rem; border-radius: 50%; background: rgba(59,130,246,0.15); border: 1px solid rgba(59,130,246,0.3); color: #60a5fa; display: flex; align-items: center; justify-content: center; font-weight: 700; font-size: 0.9rem; flex-shrink: 0; }}
.slide-content .step-content {{ flex: 1; padding-top: 0.25rem; }}
.slide-content pre {{ background: #0f172a; border: 1px solid #334155; border-radius: 8px; padding: 1rem; overflow-x: auto; margin: 0.75rem 0; }}
.slide-content code {{ font-family: 'SF Mono', 'Fira Code', monospace; font-size: 0.9em; }}
.slide-content :not(pre) > code {{ background: #334155; padding: 0.15em 0.4em; border-radius: 4px; color: #e2e8f0; }}
.slide-content table {{ width: 100%; border-collapse: collapse; margin: 0.75rem 0; }}
.slide-content th {{ text-align: left; padding: 0.5rem 0.75rem; background: rgba(255,255,255,0.05); border-bottom: 1px solid #475569; font-weight: 600; color: #f1f5f9; }}
.slide-content td {{ padding: 0.5rem 0.75rem; border-bottom: 1px solid rgba(255,255,255,0.06); }}
.slide-content .badge {{ display: inline-block; padding: 0.15rem 0.6rem; border-radius: 9999px; font-size: 0.75rem; font-weight: 600; }}
.slide-content .badge-blue {{ background: rgba(59,130,246,0.15); color: #60a5fa; }}
.slide-content .badge-amber {{ background: rgba(251,191,36,0.15); color: #fbbf24; }}
.slide-content .badge-green {{ background: rgba(16,185,129,0.15); color: #34d399; }}
.slide-content .badge-purple {{ background: rgba(139,92,246,0.15); color: #a78bfa; }}
.slide-content .divider {{ border-top: 1px solid rgba(255,255,255,0.08); margin: 1rem 0; }}

/* ── Seamless iframe (interactive mode) ── */
.slide-iframe {{ width: 100%; border: none; overflow: visible; display: block; min-height: 600px; }}
</style>
</head>
<body>

<!-- Top bar: header + navigation merged -->
<div class="topbar">
    <div class="topbar-left">
        <h1>TAI Tutor - {_esc(course_code)}</h1>
        <span class="question">"{_esc(question)}"</span>
    </div>
    <div class="topbar-nav">
        <button class="nav-arrow" id="prev-btn" onclick="prevPage()" disabled>&larr;</button>
        {"".join(nav_items)}
        <button class="nav-arrow" id="next-btn" onclick="nextPage()">&rarr;</button>
    </div>
</div>

<!-- Slide area -->
<div class="slide-area">
    {"".join(page_cards)}
</div>

<script>
// Render markdown
document.querySelectorAll('script[type="text/x-markdown"]').forEach(src => {{
    const target = src.nextElementSibling;
    if (target && target.classList.contains('markdown-content')) {{
        const raw = src.textContent;
        if (raw && raw.trim()) target.innerHTML = marked.parse(raw);
    }}
}});
document.querySelectorAll('.content-section.markdown-content').forEach(el => {{
    const raw = el.textContent;
    if (raw && raw.trim()) el.innerHTML = marked.parse(raw);
}});

// Navigation
let currentPage = 0;
const pageList = [{page_indices_js}];

function goToPage(idx) {{
    document.querySelectorAll('.page-card').forEach(c => c.classList.remove('active'));
    document.querySelectorAll('.nav-dot').forEach(d => d.classList.remove('active'));
    const card = document.getElementById('page-' + idx);
    if (card) {{ card.classList.add('active'); currentPage = idx; }}
    const navIdx = pageList.indexOf(idx);
    if (navIdx >= 0) document.querySelectorAll('.nav-dot')[navIdx].classList.add('active');
    document.getElementById('prev-btn').disabled = (navIdx === 0);
    document.getElementById('next-btn').disabled = (navIdx === pageList.length - 1);
}}

function nextPage() {{ const i = pageList.indexOf(currentPage); if (i < pageList.length - 1) goToPage(pageList[i + 1]); }}
function prevPage() {{ const i = pageList.indexOf(currentPage); if (i > 0) goToPage(pageList[i - 1]); }}

// Keyboard nav
document.addEventListener('keydown', (e) => {{
    if (e.key === 'ArrowRight' || e.key === 'ArrowDown') {{ e.preventDefault(); nextPage(); }}
    if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') {{ e.preventDefault(); prevPage(); }}
}});

// Speech toggle
function toggleSpeech(btn) {{
    const section = btn.nextElementSibling;
    section.classList.toggle('open');
    btn.textContent = section.classList.contains('open') ? '\\u25BE Hide narration' : '\\u25B8 Show narration';
}}

// Auto-resize iframes via postMessage (seamless, no internal scroll)
window.addEventListener('message', (e) => {{
    if (e.data && e.data.type === 'resize') {{
        document.querySelectorAll('.slide-iframe').forEach(f => {{
            try {{
                if (f.contentWindow === e.source) {{
                    f.style.height = (e.data.height + 16) + 'px';
                }}
            }} catch(err) {{
                // file:// cross-origin: fall back to setting height on all iframes
                f.style.height = (e.data.height + 16) + 'px';
            }}
        }});
    }}
}});

// Fallback: if postMessage resize doesn't fire within 1s, auto-size iframes
setTimeout(() => {{
    document.querySelectorAll('.slide-iframe').forEach(f => {{
        if (!f.style.height || f.style.height === '') {{
            try {{
                f.style.height = (f.contentDocument.documentElement.scrollHeight + 16) + 'px';
            }} catch(e) {{}}
        }}
    }});
}}, 1000);
</script>

</body>
</html>'''


# ── Main ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Parse mode flags
    flags = {"--html", "--interactive", "--explore"}
    args = [a for a in sys.argv[1:] if a not in flags]
    mode = "explore" if "--explore" in sys.argv else ("interactive" if "--interactive" in sys.argv else ("html" if "--html" in sys.argv else "json"))

    if len(args) < 2:
        print("Usage: python demo_tutor_pages.py <course_code> <question> [--html|--interactive]")
        print()
        print("Examples:")
        print('  python demo_tutor_pages.py "CS 61A" "Explain recursion"')
        print('  python demo_tutor_pages.py "CS 61A" "Explain recursion" --html')
        print('  python demo_tutor_pages.py "CS 61A" "Explain recursion" --interactive')
        sys.exit(1)

    course_code = args[0]
    question = " ".join(args[1:])
    asyncio.run(run_pipeline(course_code, question, render_mode=mode))
