"""
Base utilities for composable prompt management.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class PromptFragment:
    """
    A reusable prompt fragment with content and documentation.

    Attributes:
        content: The prompt text content.
        description: Documentation explaining when/how to use this fragment.
    """
    content: str
    description: str = ""

    def __str__(self) -> str:
        """Return the content when converted to string."""
        return self.content


def compose(*fragments: PromptFragment, separator: str = "\n\n") -> str:
    """
    Compose multiple prompt fragments into a single string.

    Args:
        *fragments: Variable number of PromptFragment objects to combine.
        separator: String used to join fragments (default: double newline).

    Returns:
        A single string with all fragments joined by the separator.

    Example:
        >>> from app.prompts import shared, voice
        >>> system_prompt = compose(
        ...     shared.TAI_IDENTITY,
        ...     shared.TUTOR_GUIDANCE,
        ...     voice.SPEECH_FRIENDLY_STYLE,
        ... )
    """
    return separator.join(str(f) for f in fragments if f and str(f).strip())
