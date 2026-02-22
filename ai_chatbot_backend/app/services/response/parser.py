# Standard python libraries
import json
import re
from typing import Optional


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



def extract_answers(text: str, include_thinking: bool = False, include_unreadable: bool = True) -> str:
    """
    Extract markdown_content from JSON blocks structure with smooth streaming support.
    Handles both complete and partial JSON blocks to enable word-by-word streaming.
    Args:
        text: The JSON text to parse
        include_thinking: If True, prepend thinking content (for debugging/display)
        include_unreadable: If True, append unreadable content after markdown_content (for visual display)
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
                        content = _render_block_markdown(block, include_unreadable=include_unreadable)
                        if content:
                            markdown_parts.append(content)
                result_parts.append(_join_markdown_blocks(markdown_parts))
                return "".join(result_parts)
    except json.JSONDecodeError:
        pass

    # Streaming path: extract ALL markdown_content fields, including incomplete ones.
    pattern = r'(?<!\\)"markdown_content"\s*:\s*"((?:\\.|[^"\\])*)'
    markdown_parts = []
    prev_match_end = 0

    for match in re.finditer(pattern, text, re.DOTALL):
        raw_content = match.group(1)

        # Check if content ends with incomplete escape sequence
        cleaned_content = raw_content
        if raw_content.endswith('\\'):
            cleaned_content = raw_content[:-1]

        if cleaned_content:
            try:
                unescaped = json.loads('"' + cleaned_content + '"').strip()
                content = unescaped
            except json.JSONDecodeError:
                content = cleaned_content.strip()

            # Only append citation markers for complete markdown_content strings
            is_complete = match.end() < len(text) and text[match.end()] == '"'
            if is_complete and content:
                # Extract citation ids from the region between previous match and this one
                region = text[prev_match_end:match.start()]
                citations_match = re.search(
                    r'"citations"\s*:\s*\[(.*?)\]', region, re.DOTALL
                )
                if citations_match:
                    citation_parts = _extract_citation_parts_from_raw(
                        citations_match.group(1)
                    )
                    if citation_parts:
                        content += " " + " ".join(citation_parts)

            markdown_parts.append(content)

        prev_match_end = match.end()

    return _join_markdown_blocks(markdown_parts)


def _extract_citation_parts_from_raw(raw_citations: str) -> list[str]:
    """Extract citation markers with quote_text from raw JSON text of a citations array (demo)."""
    parts = []
    # Match each citation object: extract id and quote_text
    for obj_match in re.finditer(r'\{[^}]*\}', raw_citations, re.DOTALL):
        obj_text = obj_match.group(0)
        id_match = re.search(r'"id"\s*:\s*(\d+)', obj_text)
        if not id_match:
            continue
        ref_id = id_match.group(1)
        quote_match = re.search(r'"quote_text"\s*:\s*"((?:\\.|[^"\\])*)"', obj_text, re.DOTALL)
        if quote_match:
            try:
                quote = json.loads('"' + quote_match.group(1) + '"').strip()
            except json.JSONDecodeError:
                quote = quote_match.group(1).strip()
            if quote:
                parts.append(f'[Reference {ref_id}: "{quote}"]')
                continue
        parts.append(f"[Reference: {ref_id}]")
    return parts


def _render_block_markdown(block: dict, include_unreadable: bool = True) -> str:
    block_type = block.get("type")
    if not isinstance(block_type, str):
        block_type = ""
    block_type = block_type.strip()

    content = block.get("markdown_content", "")
    if not isinstance(content, str):
        content = ""

    # Preserve internal newlines; just trim outer whitespace.
    stripped = content.strip()

    # Handle unreadable content (voice tutor mode)
    unreadable = block.get("unreadable", None)
    unreadable_content = ""
    if include_unreadable and unreadable and isinstance(unreadable, str):
        unreadable_stripped = unreadable.strip()
        if unreadable_stripped:
            # Render unreadable content based on block type
            if block_type == "code_block":
                language = block.get("language")
                lang = language.strip() if isinstance(language, str) else ""
                fence = f"```{lang}".rstrip()
                unreadable_content = f"\n{fence}\n{unreadable_stripped}\n```"
            elif block_type == "math":
                unreadable_content = f"\n$$\n{unreadable_stripped}\n$$"
            else:
                # For other types, render as code block if it looks like code
                unreadable_content = f"\n```\n{unreadable_stripped}\n```"

    # If no speakable content but has unreadable, return just unreadable
    if not stripped:
        return unreadable_content.lstrip("\n") if unreadable_content else ""

    result = ""
    if block_type == "heading":
        # Backcompat: allow markdown headings already containing hashes.
        if stripped.startswith("#"):
            result = stripped
        else:
            level = block.get("level")
            if isinstance(level, int) and 1 <= level <= 6:
                prefix = "#" * level
            else:
                # Default to level 2 to match prior "## Title" guidance.
                prefix = "##"
            result = f"{prefix} {stripped}"

    elif block_type == "code_block":
        # Backcompat: allow fenced Markdown already containing ``` fences.
        if stripped.lstrip().startswith("```"):
            result = stripped
        else:
            language = block.get("language")
            lang = language.strip() if isinstance(language, str) else ""
            fence = f"```{lang}".rstrip()
            code = content.rstrip("\n")
            result = f"{fence}\n{code}\n```"

    else:
        result = stripped

    # Append citation markers with quote context (demo)
    citations = block.get("citations", [])
    if isinstance(citations, list) and citations:
        citation_parts = []
        for c in citations:
            if isinstance(c, dict) and "id" in c:
                try:
                    ref_id = str(int(c["id"]))
                except (TypeError, ValueError):
                    continue
                quote = c.get("quote_text", "")
                if isinstance(quote, str) and quote.strip():
                    citation_parts.append(f'[Reference {ref_id}: "{quote.strip()}"]')
                else:
                    citation_parts.append(f"[Reference: {ref_id}]")
        if citation_parts:
            result += " " + " ".join(citation_parts)

    # Append unreadable content if present
    if unreadable_content:
        result = result + unreadable_content

    return result


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
            # Always use double newline for proper markdown spacing
            result.append("\n\n")
    return "".join(result)
