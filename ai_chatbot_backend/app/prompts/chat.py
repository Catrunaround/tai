"""
Chat mode prompts (JSON and Markdown formats).
These prompts define output structure for text-based chat responses.
"""
from typing import List
from app.prompts.base import PromptFragment


# =============================================================================
# JSON Format Prompts
# =============================================================================

JSON_FORMAT_STRUCTURED = PromptFragment(
    content=(
        "\n\n### RESPONSE FORMAT:\n"
        "Return ONLY a single JSON object with the following format (do NOT wrap the JSON in code fences; no `<think>` tags):\n"
        "- `thinking`: A string with your internal reasoning. Use plain text; do not include system prompts or hidden instructions. Can be empty.\n"
        "- IMPORTANT: Put `thinking` first in the JSON object (before `blocks`) so it can be streamed early.\n"
        "- `blocks`: Array of content blocks, each with (in this order):\n"
        "  - `type`: One of: paragraph, heading, list_item, code_block, blockquote, table, math, callout, definition, example, summary\n"
        "  - `language`: Code language for `type=code_block` (e.g. \"python\"), or `null` for non-code blocks\n"
        "  - `citations`: Array of references [{\"id\": <ref_number>, \"quote_text\": \"exact text...\"}] - MUST come before markdown_content\n"
        "  - `markdown_content`: Content string based on the citations above. For headings, include markdown hashes directly (e.g. \"## Section Title\"). For code blocks, prefer raw code + `language` (no ``` fences).\n"
    ),
    description="JSON format with schema enforcement - simplified prompt since structure is validated externally."
)

JSON_FORMAT_PROMPT_BASED = PromptFragment(
    content=(
        "### RESPONSE FORMAT (STRICT JSON):\n"
        "You must output a SINGLE valid JSON object (do NOT wrap the JSON in code fences; no `<think>` tags; no extra text).\n"
        "Output the content in JSON. Be as detailed as the user's request and the problem complexity require.\n"
        "### JSON SCHEMA:\n"
        "{\n"
        "  \"thinking\": \"Your internal reasoning (plain text; may be empty)\",\n"
        "  \"blocks\": [\n"
        "    {\n"
        "      \"type\": \"heading\" | \"paragraph\" | \"list_item\" | \"code_block\",\n"
        "      // For headings: use markdown syntax with # in markdown_content (e.g. \"## Section Title\").\n"
        "      // For code blocks: add \"language\": \"python\" | \"js\" | ... and keep markdown_content as raw code (no ``` fences).\n"
        "      \"language\": \"python\" | null,\n"
        "      \"citations\": [ { \"id\": 1, \"quote_text\": \"Exact text...\" } ],  // MUST come before markdown_content, all from same source file\n"
        "      \"markdown_content\": \"The rich text content based on citations above. Support standard Markdown.\"\n"
        "    }\n"
        "  ]\n"
        "}\n"
    ),
    description="Original prompt-based JSON instructions (relies on model following instructions)."
)

JSON_CRITICAL_RULES = PromptFragment(
    content=(
        "### CRITICAL RULES:\n"
        "1. **Citations First**: In each block, write `citations` BEFORE `markdown_content`. The citations provide the source material for the content.\n"
        "2. **Single Source Per Block**: All citations in a block MUST reference the same source file. If you need to cite multiple files, use separate blocks.\n"
        "3. **Verbosity**: Match the user's intent. Keep simple asks concise; expand only when the task is complex or the user requests depth.\n"
        "4. **Flow**: Prefer natural paragraphs. Use multiple `paragraph` blocks to separate ideas. Use `heading`/`list_item` blocks only when they improve clarity.\n"
        "5. **Structure**: Do NOT use a fixed template. Default to `paragraph` blocks. Do not add a generic title/heading (e.g., \"Answer\", \"Overview\") unless the user asked for it or it clearly improves clarity.\n"
        "6. **Opening**: Start with a short `paragraph` block that directly addresses the user's request.\n"
    ),
    description="Critical rules for JSON block formatting."
)

JSON_RESPONSE_STYLE = PromptFragment(
    content=(
        "\nResponse style: Write in natural paragraphs (clear separation between ideas). "
        "Do not force a fixed template or heavy headings. "
        "Do not add a generic title/heading (e.g., \"Answer\", \"Overview\") unless the user asked for it or it clearly improves clarity. "
        "Avoid the pattern of a single heading followed by a single paragraph; if the response is short, just write a single paragraph. "
        "Match the user's language by default, and adjust depth to the user's intent: "
        "concise for simple asks, more detailed for complex ones or when the user requests it. "
        "Use headings or lists only when they genuinely improve clarity (e.g., steps, checklists, comparisons). "
        "When the user is solving a problem, guide with hints and questions before giving a final answer."
    ),
    description="Response style guidance for JSON output mode."
)

JSON_CITATION_RULES = PromptFragment(
    content=(
        "\nReference evidence rules: Ground concrete claims in the provided References. "
        "When a block relies on a reference, copy the exact supporting sentence into "
        "`citations[].quote_text`. Keep `markdown_content` clean (no inline citation markers)."
    ),
    description="How to handle citations in JSON output blocks."
)


# =============================================================================
# Markdown Format Prompts
# =============================================================================

MARKDOWN_STYLE = PromptFragment(
    content=(
        "Answer in clear Markdown using natural paragraphs (do not add '```markdown'). "
        "Use headings or lists only when they genuinely improve readability. "
        "When relevant, briefly mention what the reference is (e.g., textbook/notes) and what it's about. "
        "Quote the reference if needed. Do not list references at the end."
    ),
    description="Markdown formatting style for non-JSON output."
)

MARKDOWN_CITATION_RULES = PromptFragment(
    content=(
        "\nALWAYS: Refer to specific reference numbers inline using [Reference: a,b] style!!! "
        "Do not use other style like refs, 【】, Reference: [n], > *Reference: n*, [Reference: a-b] or (reference n)!!!"
        "\nDo not list references at the end."
    ),
    description="Citation format for markdown output."
)

# =============================================================================
# Regular Mode Prompts (Non-Tutor)
# =============================================================================

REGULAR_MARKDOWN_STYLE = PromptFragment(
    content=(
        "Answer in clear Markdown using natural paragraphs. "
        "Use headings or lists only when they genuinely improve readability. "
        "Be concise and direct - provide the answer without excessive explanation. "
        "When referencing materials, briefly mention what the reference is about and cite inline using [Reference: a,b] style."
    ),
    description="Plain markdown formatting for chat regular mode (non-tutor)."
)

# =============================================================================
# Tutor Mode Enhanced Prompts
# =============================================================================

TUTOR_JSON_CITATION_RULES = PromptFragment(
    content=(
        "\n### CITATION-FIRST APPROACH:\n"
        "For each block, write `citations` BEFORE `markdown_content`.\n"
        "The citations provide the foundation - assume the learner will read the original reference material.\n"
        "Your explanation in `markdown_content` should help the learner understand the cited content, not replace it.\n"
        "Ground concrete claims in the provided References. When a block relies on a reference, "
        "copy the exact supporting sentence into `citations[].quote_text`. Keep `markdown_content` clean (no inline citation markers)."
    ),
    description="Enhanced citation-first rules for tutor mode JSON output."
)


# =============================================================================
# Helper Functions
# =============================================================================

def get_format_prompts(use_structured_json: bool = False) -> List[PromptFragment]:
    """
    Get the appropriate format prompts based on JSON mode.

    Args:
        use_structured_json: If True, use simplified prompt (schema enforces structure).
                            If False, use detailed prompt-based JSON instructions.

    Returns:
        List of PromptFragment objects for the selected format.
    """
    if use_structured_json:
        return [JSON_FORMAT_STRUCTURED, JSON_CRITICAL_RULES]
    else:
        return [JSON_FORMAT_PROMPT_BASED, JSON_CRITICAL_RULES]
