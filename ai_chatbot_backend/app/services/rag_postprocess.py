# Standard python libraries
import time
import json
from dataclasses import dataclass, asdict, field
from typing import Any, List, Optional
# Third-party libraries
from vllm import SamplingParams
from vllm.sampling_params import GuidedDecodingParams
# Local libraries
from app.core.models.chat_completion import Message
import re


def _parse_json_string_token(text: str, quote_index: int) -> tuple[str, int, bool]:
    """
    Parse a JSON string token starting at the opening `"` at `quote_index`.

    Returns:
        raw_contents: The raw (still-escaped) contents between quotes.
        next_index: Index immediately after the closing quote (or end-of-text if incomplete).
        complete: True if a closing quote was found, else False (streaming/incomplete JSON).
    """
    raw_chars: list[str] = []
    index = quote_index + 1
    escape_next = False
    text_len = len(text)
    while index < text_len:
        ch = text[index]
        if escape_next:
            raw_chars.append(ch)
            escape_next = False
            index += 1
            continue
        if ch == "\\":
            raw_chars.append(ch)
            escape_next = True
            index += 1
            continue
        if ch == '"':
            return "".join(raw_chars), index + 1, True
        raw_chars.append(ch)
        index += 1
    return "".join(raw_chars), index, False


def _unescape_json_string_prefix(raw: str) -> str:
    """
    Best-effort unescape of a *prefix* of JSON string contents.

    This is streaming-friendly: it only decodes escape sequences that are complete in `raw`
    and ignores any trailing incomplete escape sequence.
    """
    if not raw:
        return ""

    out_chars: list[str] = []
    index = 0
    raw_len = len(raw)
    while index < raw_len:
        ch = raw[index]
        if ch != "\\":
            out_chars.append(ch)
            index += 1
            continue

        # Escape sequence
        if index + 1 >= raw_len:
            break
        esc = raw[index + 1]

        if esc in ['"', "\\", "/"]:
            out_chars.append(esc)
            index += 2
            continue
        if esc == "b":
            out_chars.append("\b")
            index += 2
            continue
        if esc == "f":
            out_chars.append("\f")
            index += 2
            continue
        if esc == "n":
            out_chars.append("\n")
            index += 2
            continue
        if esc == "r":
            out_chars.append("\r")
            index += 2
            continue
        if esc == "t":
            out_chars.append("\t")
            index += 2
            continue
        if esc == "u":
            hex_start = index + 2
            hex_end = index + 6
            if hex_end > raw_len:
                break
            hex_digits = raw[hex_start:hex_end]
            try:
                out_chars.append(chr(int(hex_digits, 16)))
            except ValueError:
                break
            index += 6
            continue

        # Unknown escape: best-effort emit the escaped char.
        out_chars.append(esc)
        index += 2

    return "".join(out_chars)


def _extract_top_level_json_string_field(text: str, field_name: str) -> Optional[str]:
    """
    Best-effort extraction of a top-level string field from a (possibly partial) JSON object.
    Returns the unescaped *prefix* of the string value, or None if not found / not applicable.
    """
    stripped = text.lstrip()
    if not stripped.startswith("{"):
        return None

    depth = 0
    index = 0
    text_len = len(stripped)

    while index < text_len:
        ch = stripped[index]
        if ch == '"':
            raw_string, after_string_index, complete = _parse_json_string_token(stripped, index)
            if not complete:
                return None

            key_candidate = _unescape_json_string_prefix(raw_string)
            cursor = after_string_index
            while cursor < text_len and stripped[cursor].isspace():
                cursor += 1

            # Only treat as an object key when followed by ':' at top-level (depth == 1).
            if depth == 1 and cursor < text_len and stripped[cursor] == ":":
                cursor += 1
                while cursor < text_len and stripped[cursor].isspace():
                    cursor += 1

                if key_candidate == field_name:
                    if cursor >= text_len:
                        return ""
                    if stripped[cursor] != '"':
                        return ""
                    raw_value, _, _ = _parse_json_string_token(stripped, cursor)
                    return _unescape_json_string_prefix(raw_value)

            index = after_string_index
            continue

        if ch == "{":
            depth += 1
        elif ch == "}":
            depth = max(0, depth - 1)

        index += 1

    return None


def extract_channels(text: str) -> dict:
    """
    Best-effort extraction of "analysis" vs "final" from models that emit `<think>...</think>`
    wrappers (common in "thinking" tuned OSS models).

    - If the output starts with a `<think>` block, treat its contents as `analysis` and everything
      after the closing tag as `final`.
    - Otherwise, treat the entire text as `final` (important for JSON-guided decoding where no
      think wrapper is present).
    """
    if not text:
        return {"analysis": "", "final": ""}

    # Only treat `<think>...</think>` as a wrapper when it is a leading block.
    if re.match(r"^\s*<think>", text):
        if "</think>" in text:
            # Use a regex to avoid false splits on `</think>` appearing later in JSON strings.
            m = re.match(r"^\s*<think>\s*(?P<analysis>.*?)\s*</think>\s*(?P<final>.*)\Z", text, re.DOTALL)
            if m:
                return {"analysis": m.group("analysis").strip(), "final": m.group("final").strip()}

            parts = text.split("</think>", 1)
            return {"analysis": parts[0].strip(), "final": parts[1].strip()}

        # Streaming: `<think>` started but hasn't closed yet.
        incomplete_patterns = ["</think", "</", "<"]
        cleaned_text = text
        for pattern in incomplete_patterns:
            if text.endswith(pattern):
                cleaned_text = text[:-len(pattern)]
                break
        return {"analysis": cleaned_text.strip(), "final": ""}

    # No think wrapper → everything is final (supports pure-JSON outputs).
    thinking = _extract_top_level_json_string_field(text, "thinking")
    if thinking is not None:
        return {"analysis": thinking.strip(), "final": text.strip()}
    return {"analysis": "", "final": text.strip()}



def extract_answers(text: str, include_thinking: bool = False) -> str:
    """
    Extract markdown_content from JSON blocks structure with smooth streaming support.
    Handles both complete and partial JSON blocks to enable word-by-word streaming.
    Expected formats:
    1. Original format (prompt-based):
       {
         "blocks": [
           {"type": "...", "markdown_content": "...", "citations": [...]},
           ...
         ]
       }

    2. (Legacy) Structured format with an optional `thinking` field.

    Args:
        text: The JSON text to parse
        include_thinking: If True, prepend thinking content (for debugging/display)
    Returns: Concatenated markdown_content from all blocks (including partial content)
    """
    if not text.strip():
        return ""
    result_parts = []

    # Try full JSON parse first (fast path for complete JSON)
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            # Extract legacy thinking if present and requested
            if include_thinking and "thinking" in data:
                thinking = data.get("thinking", "").strip()
                if thinking:
                    result_parts.append(f"*Thinking: {thinking}*\n\n")

            # Extract blocks
            if "blocks" in data:
                markdown_parts = []
                for block in data.get("blocks", []):
                    if isinstance(block, dict):
                        content = _render_block_markdown(block)
                        if content:
                            markdown_parts.append(content)
                result_parts.append(_join_markdown_blocks(markdown_parts))
                return "".join(result_parts)
    except json.JSONDecodeError:
        pass

    # Streaming path: extract ALL markdown_content fields, including incomplete ones.
    # Must handle escaped quotes (e.g., \" inside code blocks / JSON snippets) and partial strings.
    #
    # Pattern matches both:
    # - Complete: "markdown_content": "content here"
    # - Incomplete: "markdown_content": "partial content (no closing quote yet)
    #
    # Notes:
    # - `(?<!\\)` avoids matching escaped quotes that could appear inside JSON strings.
    # - `(?:\\.|[^"\\])*` captures valid JSON string content, including escaped quotes.
    pattern = r'(?<!\\)"markdown_content"\s*:\s*"((?:\\.|[^"\\])*)'
    markdown_parts = []

    for match in re.finditer(pattern, text, re.DOTALL):
        raw_content = match.group(1)

        # Check if content ends with incomplete escape sequence
        # Don't include trailing backslash that might be part of \n, \", etc.
        cleaned_content = raw_content
        if raw_content.endswith('\\'):
            cleaned_content = raw_content[:-1]

        if cleaned_content:
            try:
                # Try to properly unescape JSON escape sequences
                # Wrap in quotes to make it valid JSON string for parsing
                unescaped = json.loads('"' + cleaned_content + '"').strip()
                markdown_parts.append(unescaped)
            except json.JSONDecodeError:
                # If unescaping fails (malformed escapes), use raw content
                # This handles edge cases during streaming
                markdown_parts.append(cleaned_content.strip())

    return _join_markdown_blocks(markdown_parts)


def _render_block_markdown(block: dict) -> str:
    block_type = block.get("type")
    if not isinstance(block_type, str):
        block_type = ""
    block_type = block_type.strip()

    content = block.get("markdown_content", "")
    if not isinstance(content, str):
        return ""

    # Preserve internal newlines; just trim outer whitespace.
    stripped = content.strip()
    if not stripped:
        return ""

    if block_type == "heading":
        # Backcompat: allow markdown headings already containing hashes.
        if stripped.startswith("#"):
            return stripped
        level = block.get("level")
        if isinstance(level, int) and 1 <= level <= 6:
            prefix = "#" * level
        else:
            # Default to level 2 to match prior "## Title" guidance.
            prefix = "##"
        return f"{prefix} {stripped}"

    if block_type == "code_block":
        # Backcompat: allow fenced Markdown already containing ``` fences.
        if stripped.lstrip().startswith("```"):
            return stripped
        language = block.get("language")
        lang = language.strip() if isinstance(language, str) else ""
        fence = f"```{lang}".rstrip()
        code = content.rstrip("\n")
        return f"{fence}\n{code}\n```"

    return stripped


def _join_markdown_blocks(parts: list[str]) -> str:
    """
    Join markdown blocks with proper spacing for headers and other elements.
    Ensures markdown headers render correctly by adding appropriate blank lines.
    """
    if not parts:
        return ""

    result = []
    for i, part in enumerate(parts):
        if not part:
            continue
        # Add the content
        result.append(part)

        # Add spacing after this block (except for the last block)
        if i < len(parts) - 1:
            next_part = parts[i + 1] if i + 1 < len(parts) else ""

            # Check if current part ends with a heading or next part starts with one
            current_is_heading = part.strip().startswith('#')
            next_is_heading = next_part.strip().startswith('#') if next_part else False

            # Always use double newline for proper markdown spacing
            # This ensures headers have blank lines before them
            result.append("\n\n")
    return "".join(result)


# Environment variables
MEMORY_SYNOPSIS_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "focus": {"type": "string"},
        "user_goals": {"type": "array", "items": {"type": "string"}},
        "constraints": {"type": "array", "items": {"type": "string"}},
        "key_entities": {"type": "array", "items": {"type": "string"}},
        "artifacts": {"type": "array", "items": {"type": "string"}},
        "open_questions": {"type": "array", "items": {"type": "string"}},
        "action_items": {"type": "array", "items": {"type": "string"}},
        "decisions": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["focus", "user_goals", "constraints", "key_entities",
                 "artifacts", "open_questions", "action_items", "decisions"],
    "additionalProperties": False
}
GUIDED = GuidedDecodingParams(json=MEMORY_SYNOPSIS_JSON_SCHEMA)
SAMPLING_JSON = SamplingParams(
    temperature=0.0, top_p=1.0, max_tokens=800, guided_decoding=GUIDED, skip_special_tokens=False
)

# ========================
# Response Blocks JSON Schema (for structured output mode)
# ========================
# This schema enforces valid JSON output format for chat responses.
# Use this with response_format parameter (OpenAI) or GuidedDecodingParams (VLLM)
# to guarantee structurally valid JSON instead of relying on prompt instructions.

CITATION_SCHEMA = {
    "type": "object",
    "properties": {
        "id": {
            "type": "integer",
            "description": "Reference number from the provided context"
        },
        "quote_text": {
            "type": "string",
            "description": "Exact quoted text from the reference"
        }
    },
    "required": ["id", "quote_text"],
    "additionalProperties": False
}

BLOCK_SCHEMA = {
    "type": "object",
    "properties": {
        "type": {
            "type": "string",
            "enum": [
                "heading",           # Section headers with markdown hashes (e.g., "## Title")
                "paragraph",         # Standard text paragraphs
                "list_item",         # Bullet or numbered list items
                "code_block",        # Code snippets with syntax highlighting
                "blockquote",        # Quoted content
                "table",             # Markdown tables
                "math",              # Mathematical expressions (LaTeX)
                "callout",           # Important notes, warnings, tips
                "definition",        # Term definitions
                "example",           # Examples or illustrations
                "summary",           # Summary or conclusion blocks
            ],
            "description": "The type of content block"
        },
        "language": {
            "type": "string",
            "description": "Programming language for code blocks (e.g., 'python', 'javascript'). Use only when type is 'code_block'."
        },
        "markdown_content": {
            "type": "string",
            "description": "Rich text content in Markdown format. For headings, include markdown hashes (e.g., '## Title') directly in markdown_content. For code blocks, either include raw code here with `language`, or include fenced Markdown."
        },
        "citations": {
            "type": "array",
            "items": CITATION_SCHEMA,
            "description": "Citations referencing the provided context"
        }
    },
    "required": ["type", "markdown_content", "citations"],
    "additionalProperties": False
}

RESPONSE_BLOCKS_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "thinking": {
            "type": "string",
            "description": "Optional reasoning/scratchpad text. Leave empty when not needed.",
        },
        "blocks": {
            "type": "array",
            "items": BLOCK_SCHEMA,
            "description": "Array of content blocks forming the response"
        }
    },
    "required": ["thinking", "blocks"],
    "additionalProperties": False
}

# OpenAI response_format compatible schema (for use with response_format parameter)
RESPONSE_BLOCKS_OPENAI_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "chat_response_blocks",
        "strict": True,
        "schema": RESPONSE_BLOCKS_JSON_SCHEMA
    }
}

# VLLM GuidedDecodingParams for structured response blocks
GUIDED_RESPONSE_BLOCKS = GuidedDecodingParams(json=RESPONSE_BLOCKS_JSON_SCHEMA)


@dataclass
class MemorySynopsis:
    """
    Compact, structured memory about a conversation. Keep it small & stable.
    """
    focus: str = ""                                             # What is the main topic / intent of the user?
    user_goals: List[str] = field(default_factory=list)         # User's explicit goals/preferences
    constraints: List[str] = field(default_factory=list)        # Hard constraints (versions, dates, scope, etc.)
    key_entities: List[str] = field(default_factory=list)       # People, products, datasets, repos, courses…
    artifacts: List[str] = field(default_factory=list)          # Files, URLs, IDs, paths mentioned
    open_questions: List[str] = field(default_factory=list)     # Unresolved questions the user asked
    action_items: List[str] = field(default_factory=list)       # TODOs, “next steps”
    decisions: List[str] = field(default_factory=list)          # Agreed choices so far

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)

    @staticmethod
    def from_json(s: str) -> "MemorySynopsis":
        data = json.loads(s or "{}")
        return MemorySynopsis(**{k: data.get(k, v) for k, v in asdict(MemorySynopsis()).items()})


async def build_memory_synopsis(
        messages: List[Message],
        tokenizer: Any,
        engine: Any,
        prev_synopsis: Optional[MemorySynopsis] = None,
        chat_history_sid: Optional[str] = None,
        max_prompt_tokens: int = 3500,
) -> MemorySynopsis:
    """
    Create/refresh the rolling MemorySynopsis.
    - messages: full chat so far (system/assistant/user)
    - prev_synopsis: prior memory to carry forward (we'll merge)
    - chat_history_sid: if provided, retrieves previous memory from MongoDB
    """
    # Graceful MongoDB retrieval for previous memory
    if chat_history_sid and not prev_synopsis:
        try:
            from app.services.memory_synopsis_service import MemorySynopsisService
            memory_service = MemorySynopsisService()
            prev_synopsis = await memory_service.get_by_chat_history_sid(chat_history_sid)
        except Exception as e:
            print(f"[INFO] Failed to retrieve previous memory, generating from scratch: {e}")
            prev_synopsis = None  # Continue without previous memory

    transcript = _render_transcript(messages)
    cur = await _llm_synopsis_from_transcript(engine, tokenizer, transcript, max_prompt_tokens=max_prompt_tokens)
    if prev_synopsis:
        cur = await _llm_merge_synopses(engine, tokenizer, prev_synopsis, cur)

    # tighten fields (keep stable, short)
    cur.focus = _truncate_sentence(cur.focus, 180)
    cur.user_goals = cur.user_goals[:8]
    cur.constraints = cur.constraints[:8]
    cur.key_entities = cur.key_entities[:16]
    cur.artifacts = cur.artifacts[:16]
    cur.open_questions = cur.open_questions[:8]
    cur.action_items = cur.action_items[:8]
    cur.decisions = cur.decisions[:8]
    return cur


_LLM_SYSTEM = (
    "You are a memory-synopsis compressor. "
    "Given a chat transcript, produce a STRUCTURED JSON with keys: "
    "focus (string), user_goals (list[str]), constraints (list[str]), key_entities (list[str]), "
    "artifacts (list[str]), open_questions (list[str]), action_items (list[str]), decisions (list[str]). "
    "\nHere's some description of each key: \n"
    "focus - what is the main topic / intent of the user? \n"
    "user_goals - user's explicit goals/preferences. \n"
    "constraints - hard constraints (versions, dates, scope, etc.). \n"
    "key_entities - people, products, datasets, repos, courses… \n"
    "artifacts - files, URLs, IDs, paths mentioned. \n"
    "open_questions - unresolved questions the user asked. \n"
    "action_items - TODOs, “next steps”. \n"
    "decisions - agreed choices so far. \n"
    "\nRules:\n"
    "- Return ONLY a single JSON object that matches the schema keys and types above.\n"
    "- Keep text terse and factual. No markdown, no code fences, no extra commentary.\n"
    "- Arrays must contain strings only; deduplicate items; remove empty strings.\n"
    "- Extract explicit constraints (versions, dates, scope limits) as strings.\n"
)

_LLM_USER_TEMPLATE = """Transcript:
{transcript}

Requirements:
- Summarize tersely.
- Deduplicate entities and URLs/paths.
- Extract explicit constraints (versions, dates, scope limits).
Return ONLY JSON.
"""


async def _llm_synopsis_from_transcript(
        engine: Any,
        tokenizer: Any,
        transcript: str,
        max_prompt_tokens: int = 3500,
) -> MemorySynopsis:
    """
    Use local engine to compress the transcript into MemorySynopsis JSON.
    """
    # Prepare the system and user messages for the LLM
    sys_msg = {"role": "system", "content": _LLM_SYSTEM}
    usr = {
        "role": "user",
        "content": _LLM_USER_TEMPLATE.format(
            transcript=_truncate_to_tokens(tokenizer, transcript, max_prompt_tokens)
        )
    }
    chat = [sys_msg, usr]
    prompt = tokenizer.apply_chat_template(chat, tokenize=False, add_generation_prompt=True)
    # Generate the synopsis using the engine
    text = ""
    async for chunk in engine.generate(
            prompt=prompt,
            sampling_params=SAMPLING_JSON,
            request_id=str(time.time_ns())
    ):
        text = chunk.outputs[0].text
    text = extract_channels(text).get('final', "{}")
    print('Generated MemorySynopsis JSON:', text)
    try:
        data = json.loads(text.strip())
    except json.JSONDecodeError:
        print('Failed to parse merged MemorySynopsis JSON:', text)
        return MemorySynopsis()
    return MemorySynopsis(**data)


def _render_transcript(messages: List[Message], max_chars: int = 12000) -> str:
    """
    Linearized transcript with role tags. Keep it simple for robustness.
    """
    lines: List[str] = []
    for m in messages:
        role = (getattr(m, "role", None) or "user").lower()
        content = getattr(m, "content", "").strip()
        lines.append(f"{role.capitalize()}: {content}")
    text = "\n".join(lines)
    return text if len(text) <= max_chars else text[-max_chars:]


def _safe_token_len(tokenizer: Any, text: str) -> int:
    """
    Safely estimate the number of tokens in a text using the tokenizer.
    """
    return len(tokenizer.encode(text, add_special_tokens=False))


def _truncate_to_tokens(tokenizer: Any, text: str, max_tokens: int) -> str:
    """
    Truncate text to fit within the max_tokens limit using binary search.
    """
    if _safe_token_len(tokenizer, text) <= max_tokens:
        return text
    # binary chop by characters (fast & simple)
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi) // 2
        if _safe_token_len(tokenizer, text[:mid]) <= max_tokens:
            lo = mid + 1
        else:
            hi = mid
    return text[:max(0, lo - 1)]


def _truncate_sentence(s: str, max_chars: int) -> str:
    return s if len(s) <= max_chars else s[:max_chars - 1] + "…"


_LLM_MERGE_SYSTEM = (
    "You merge two conversation memory synopses into ONE, preserving correctness and recency.\n"
    "Output ONLY a JSON object with exactly these keys and types:\n"
    "focus (string), user_goals (list[str]), constraints (list[str]), key_entities (list[str]),\n"
    "artifacts (list[str]), open_questions (list[str]), action_items (list[str]), decisions (list[str]).\n"
    "Rules:\n"
    "- Prefer NEW facts if they add specificity, dates/versions/IDs, or fix errors.\n"
    "- Keep stable facts from OLD if NEW is generic or contradictory.\n"
    "- Deduplicate items; remove empties; keep terse phrasing.\n"
    "- Enforce keeping the most specific and recent at the front of lists.\n"
    "- Do NOT invent facts that are not present in OLD or NEW.\n"
    "- Return ONLY JSON. No markdown, no commentary."
)

_LLM_MERGE_USER_TEMPLATE = """OLD_SYNOPSIS:
{old_json}

NEW_SYNOPSIS:
{new_json}

Task:
Produce the single best merged synopsis following the rules. Return ONLY JSON.
"""


async def _llm_merge_synopses(
    engine: Any,
    tokenizer: Any,
    old: MemorySynopsis,
    new: MemorySynopsis,
) -> MemorySynopsis:
    old_json = MemorySynopsis(**asdict(old)).to_json()
    new_json = MemorySynopsis(**asdict(new)).to_json()
    # Prepare the system and user messages for the LLM
    sys_msg = {"role": "system", "content": _LLM_MERGE_SYSTEM}
    usr_msg = {"role": "user", "content": _LLM_MERGE_USER_TEMPLATE.format(old_json=old_json, new_json=new_json)}
    prompt = tokenizer.apply_chat_template([sys_msg, usr_msg], tokenize=False, add_generation_prompt=True)
    # Generate the merged synopsis using the engine
    text = ""
    async for chunk in engine.generate(
            prompt=prompt,
            sampling_params=SAMPLING_JSON,
            request_id=str(time.time_ns())
    ):
        text = chunk.outputs[0].text
    text = extract_channels(text).get('final', "{}")
    # try to parse JSON, if fails return empty MemorySynopsis
    try:
        data = json.loads(text.strip())
    except json.JSONDecodeError:
        print('Failed to parse merged MemorySynopsis JSON:', text)
        return MemorySynopsis()
    return MemorySynopsis(**data)
