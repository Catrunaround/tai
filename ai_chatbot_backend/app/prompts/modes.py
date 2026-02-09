"""
4-Mode System Configuration.

This module provides the Mode enum, ModeConfig dataclass, and functions
to get mode configurations. The actual prompts live in the textchat/
and voice/ subfolders for easy editing.

4-Mode System:
- TEXT_CHAT_TUTOR: tutor_mode=True, audio_response=False
- TEXT_CHAT_REGULAR: tutor_mode=False, audio_response=False
- VOICE_TUTOR: tutor_mode=True, audio_response=True
- VOICE_REGULAR: tutor_mode=False, audio_response=True
"""

from dataclasses import dataclass
from enum import Enum, auto
from typing import Union

# Import prompts from subfolders
from app.prompts.textchat import (
    TUTOR_PROMPT as TEXT_CHAT_TUTOR_PROMPT,
    REGULAR_PROMPT as TEXT_CHAT_REGULAR_PROMPT,
    TUTOR_ADDENDUM_WITH_REFS as TEXT_CHAT_TUTOR_ADDENDUM_WITH_REFS,
    TUTOR_ADDENDUM_NO_REFS as TEXT_CHAT_TUTOR_ADDENDUM_NO_REFS,
    REGULAR_ADDENDUM_WITH_REFS as TEXT_CHAT_REGULAR_ADDENDUM_WITH_REFS,
    REGULAR_ADDENDUM_NO_REFS as TEXT_CHAT_REGULAR_ADDENDUM_NO_REFS,
)
from app.prompts.voice import (
    TUTOR_PROMPT as VOICE_TUTOR_PROMPT,
    REGULAR_PROMPT as VOICE_REGULAR_PROMPT,
    TUTOR_ADDENDUM_WITH_REFS as VOICE_TUTOR_ADDENDUM_WITH_REFS,
    TUTOR_ADDENDUM_NO_REFS as VOICE_TUTOR_ADDENDUM_NO_REFS,
    REGULAR_ADDENDUM_WITH_REFS as VOICE_REGULAR_ADDENDUM_WITH_REFS,
    REGULAR_ADDENDUM_NO_REFS as VOICE_REGULAR_ADDENDUM_NO_REFS,
)


class Mode(Enum):
    """Enumeration of the 4 operating modes."""
    TEXT_CHAT_TUTOR = auto()    # tutor_mode=True, audio_response=False
    TEXT_CHAT_REGULAR = auto()  # tutor_mode=False, audio_response=False
    VOICE_TUTOR = auto()        # tutor_mode=True, audio_response=True
    VOICE_REGULAR = auto()      # tutor_mode=False, audio_response=True


@dataclass(frozen=True)
class ModeConfig:
    """Complete configuration for a mode - all prompts in one place."""
    mode: Mode
    system_prompt: str
    system_addendum_with_refs: Union[str, dict]  # str: append | dict: template fill
    system_addendum_no_refs: Union[str, dict]    # str: append | dict: template fill
    is_tutor: bool
    is_audio: bool


# Registry - single source of truth for all mode configurations
MODE_CONFIGS = {
    Mode.TEXT_CHAT_TUTOR: ModeConfig(
        mode=Mode.TEXT_CHAT_TUTOR,
        system_prompt=TEXT_CHAT_TUTOR_PROMPT,
        system_addendum_with_refs=TEXT_CHAT_TUTOR_ADDENDUM_WITH_REFS,
        system_addendum_no_refs=TEXT_CHAT_TUTOR_ADDENDUM_NO_REFS,
        is_tutor=True,
        is_audio=False,
    ),
    Mode.TEXT_CHAT_REGULAR: ModeConfig(
        mode=Mode.TEXT_CHAT_REGULAR,
        system_prompt=TEXT_CHAT_REGULAR_PROMPT,
        system_addendum_with_refs=TEXT_CHAT_REGULAR_ADDENDUM_WITH_REFS,
        system_addendum_no_refs=TEXT_CHAT_REGULAR_ADDENDUM_NO_REFS,
        is_tutor=False,
        is_audio=False,
    ),
    Mode.VOICE_TUTOR: ModeConfig(
        mode=Mode.VOICE_TUTOR,
        system_prompt=VOICE_TUTOR_PROMPT,
        system_addendum_with_refs=VOICE_TUTOR_ADDENDUM_WITH_REFS,
        system_addendum_no_refs=VOICE_TUTOR_ADDENDUM_NO_REFS,
        is_tutor=True,
        is_audio=True,
    ),
    Mode.VOICE_REGULAR: ModeConfig(
        mode=Mode.VOICE_REGULAR,
        system_prompt=VOICE_REGULAR_PROMPT,
        system_addendum_with_refs=VOICE_REGULAR_ADDENDUM_WITH_REFS,
        system_addendum_no_refs=VOICE_REGULAR_ADDENDUM_NO_REFS,
        is_tutor=False,
        is_audio=True,
    ),
}


def get_mode(tutor_mode: bool, audio_response: bool) -> Mode:
    """Map boolean flags to Mode enum."""
    if audio_response:
        return Mode.VOICE_TUTOR if tutor_mode else Mode.VOICE_REGULAR
    else:
        return Mode.TEXT_CHAT_TUTOR if tutor_mode else Mode.TEXT_CHAT_REGULAR


def get_mode_config(tutor_mode: bool, audio_response: bool) -> ModeConfig:
    """
    Get complete mode configuration in one call.

    This is the main entry point for getting all prompts for a mode.
    Replaces scattered if/else logic with a single lookup.

    Args:
        tutor_mode: If True, use tutor behavior (hints-first, JSON output)
        audio_response: If True, output will be converted to speech

    Returns:
        ModeConfig with all prompts and settings for the mode
    """
    mode = get_mode(tutor_mode, audio_response)
    return MODE_CONFIGS[mode]


def get_complete_system_prompt(
    tutor_mode: bool,
    audio_response: bool,
    has_refs: bool,
    course: str = "",
    class_name: str = ""
) -> str:
    """
    Get the complete assembled prompt the model receives.

    This returns the exact prompt sent to the model, with all fragments
    assembled and placeholders filled in. Useful for debugging and testing.

    Args:
        tutor_mode: If True, use tutor behavior (hints-first, JSON output)
        audio_response: If True, output will be converted to speech
        has_refs: If True, use addendum for when references are found
        course: Course identifier (e.g., "CS101")
        class_name: Class name for context (e.g., "Intro to Python")

    Returns:
        Complete assembled system prompt string
    """
    config = get_mode_config(tutor_mode, audio_response)
    addendum = config.system_addendum_with_refs if has_refs else config.system_addendum_no_refs
    if isinstance(addendum, dict):
        # Template-based: fill category extensions into the system prompt
        resolved = {k: v.format(course=course, class_name=class_name) for k, v in addendum.items()}
        return config.system_prompt.format(**resolved)
    else:
        # Legacy string: format and append
        addendum = addendum.format(course=course, class_name=class_name)
        return config.system_prompt + addendum


def get_system_prompt(tutor_mode: bool, audio_response: bool) -> str:
    """
    Get the complete system prompt for the specified mode.

    Args:
        tutor_mode: If True, use tutor behavior (hints-first, JSON output)
        audio_response: If True, output will be converted to speech

    Returns:
        Complete system prompt string for the mode
    """
    return get_mode_config(tutor_mode, audio_response).system_prompt


# =============================================================================
# MODE SUMMARY (for quick reference)
# =============================================================================
"""
┌─────────────────┬──────────────┬──────────────────┬─────────────────────────────┐
│ Mode            │ tutor_mode   │ audio_response   │ Output Format               │
├─────────────────┼──────────────┼──────────────────┼─────────────────────────────┤
│ TEXT_CHAT_TUTOR │ True         │ False            │ JSON {thinking, blocks[]}   │
│ TEXT_CHAT_REG   │ False        │ False            │ Markdown + [Reference: n]   │
│ VOICE_TUTOR     │ True         │ True             │ JSON with unreadable field  │
│ VOICE_REGULAR   │ False        │ True             │ Plain speakable text        │
└─────────────────┴──────────────┴──────────────────┴─────────────────────────────┘
"""
