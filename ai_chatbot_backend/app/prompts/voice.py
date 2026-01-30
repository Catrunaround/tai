"""
Voice mode ONLY prompts.
These prompts are specifically for audio/speech responses.
"""
from app.prompts.base import PromptFragment


# =============================================================================
# Voice Regular Mode (audio_response=True, tutor_mode=False)
# =============================================================================

VOICE_REGULAR_STYLE = PromptFragment(
    content="""STYLE:
Use a speaker-friendly tone. Try to end every sentence with a period '.'. ALWAYS: Avoid code block, Markdown formatting or math equation!!! No references at the end or listed without telling usage.
Make the first sentence short and engaging. If no instruction is given, explain that you did not hear any instruction. Discuss what the reference is, such as a textbook or sth, and what the reference is about. Quote the reference if needed.
Do not use symbols that are not readable in speech, such as (, ), [, ], {, }, <, >, *, #, -, !, $, %, ^, &, =, +, \\, /, ~, `, etc. In this way, avoid code, Markdown formatting or math equation!!!""",
    description="Speech-friendly formatting for voice regular mode - no markdown, code, or unreadable symbols."
)

# Keep SPEECH_FRIENDLY_STYLE as alias for backward compatibility
SPEECH_FRIENDLY_STYLE = VOICE_REGULAR_STYLE

SPEAKABLE_REFERENCES = PromptFragment(
    content=(
        "\nREFERENCE USAGE:"
        "\nMention specific reference numbers inline when that part of the answer is refer to some reference. "
        "Discuss what the reference is, such as a textbook or sth, and what the reference is about. Quote the reference if needed. "
        "\nALWAYS: Do not mention references in a unreadable format like refs, 【】, Reference: [n], > *Reference: n* or (reference n)!!! "
        "Those are not understandable since the output is going to be converted to speech."
    ),
    description="How to cite references in a speakable format for voice output."
)

# =============================================================================
# Voice Tutor Mode (audio_response=True, tutor_mode=True)
# =============================================================================

VOICE_TUTOR_FORMAT = PromptFragment(
    content=(
        "### RESPONSE FORMAT (VOICE TUTOR MODE):\n"
        "Return ONLY a single JSON object with the following format (do NOT wrap the JSON in code fences; no `<think>` tags):\n"
        "- `thinking`: A string with your internal reasoning. Use plain text. Can be empty.\n"
        "- IMPORTANT: Put `thinking` first in the JSON object (before `blocks`) so it can be streamed early.\n"
        "- `blocks`: Array of content blocks, each with (in this order):\n"
        "  - `type`: One of: paragraph, heading, list_item, code_block, blockquote, table, math, callout, definition, example, summary\n"
        "  - `language`: Code language for `type=code_block` (e.g. \"python\"), or `null` for non-code blocks\n"
        "  - `citations`: Array of references [{\"id\": <ref_number>, \"quote_text\": \"exact text...\"}] - MUST come before markdown_content\n"
        "  - `markdown_content`: SPEAKABLE content ONLY. Write text that can be read aloud naturally.\n"
        "  - `unreadable`: Content that CANNOT be spoken aloud (code, formulas, tables, complex symbols). This is shown visually to the student but NOT read by text-to-speech. Set to `null` if all content is speakable.\n"
    ),
    description="JSON format with unreadable property for voice tutor mode."
)

VOICE_TUTOR_UNREADABLE_RULES = PromptFragment(
    content=(
        "### UNREADABLE CONTENT RULES:\n"
        "The `unreadable` field contains content that will be SHOWN visually but NOT spoken aloud.\n"
        "Put in `unreadable`:\n"
        "  - Code snippets and code blocks\n"
        "  - Mathematical formulas and equations\n"
        "  - Tables and structured data\n"
        "  - Complex symbols, special characters\n"
        "  - URLs, file paths, technical identifiers\n"
        "\n"
        "Put in `markdown_content` (speakable):\n"
        "  - Natural language explanations\n"
        "  - Verbal descriptions of what the code/formula does\n"
        "  - Step-by-step guidance in conversational tone\n"
        "  - Simple numbers and basic punctuation\n"
        "\n"
        "Example: Instead of reading code, say 'The function takes two parameters and returns their sum' in markdown_content, "
        "and put the actual code in unreadable."
    ),
    description="Rules for what goes in unreadable vs markdown_content in voice tutor mode."
)
