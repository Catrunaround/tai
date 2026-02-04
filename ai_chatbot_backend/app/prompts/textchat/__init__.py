"""
Text Chat mode prompts (TEXT_CHAT_TUTOR and TEXT_CHAT_REGULAR).

These modes output structured content for text-based chat interfaces.
"""
from .tutor import SYSTEM_PROMPT as TUTOR_PROMPT
from .regular import SYSTEM_PROMPT as REGULAR_PROMPT
from .references import (
    TUTOR_ADDENDUM_WITH_REFS,
    TUTOR_ADDENDUM_NO_REFS,
    REGULAR_ADDENDUM_WITH_REFS,
    REGULAR_ADDENDUM_NO_REFS,
)

__all__ = [
    "TUTOR_PROMPT",
    "REGULAR_PROMPT",
    "TUTOR_ADDENDUM_WITH_REFS",
    "TUTOR_ADDENDUM_NO_REFS",
    "REGULAR_ADDENDUM_WITH_REFS",
    "REGULAR_ADDENDUM_NO_REFS",
]
