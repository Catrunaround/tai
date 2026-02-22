"""
Text Chat mode prompts (TEXT_CHAT_TUTOR and TEXT_CHAT_REGULAR).

These modes output structured content for text-based chat interfaces.
"""
from .tutor import SYSTEM_PROMPT_WITH_REFS as TUTOR_PROMPT_WITH_REFS
from .tutor import SYSTEM_PROMPT_NO_REFS as TUTOR_PROMPT_NO_REFS
from .regular import SYSTEM_PROMPT_WITH_REFS as REGULAR_PROMPT_WITH_REFS
from .regular import SYSTEM_PROMPT_NO_REFS as REGULAR_PROMPT_NO_REFS

__all__ = [
    "TUTOR_PROMPT_WITH_REFS",
    "TUTOR_PROMPT_NO_REFS",
    "REGULAR_PROMPT_WITH_REFS",
    "REGULAR_PROMPT_NO_REFS",
]
