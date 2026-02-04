"""
Composable Prompt Management System for TAI.

This module provides reusable prompt fragments and complete mode prompts
that can be combined dynamically at runtime.

Usage:
    from app.prompts import modes, memory
    from app.prompts.base import compose, PromptFragment

    # Get complete system prompt for a mode
    system_prompt = modes.get_system_prompt(tutor_mode=True, audio_response=False)

    # Use response style constants for augmented prompts
    style = modes.CHAT_TUTOR_RESPONSE_STYLE

Prompt Modules:
    - modes: Complete 4-mode system prompts (TEXT_CHAT_TUTOR, TEXT_CHAT_REGULAR, VOICE_TUTOR, VOICE_REGULAR)
    - memory: Synopsis compression, merge prompts (memory service)
    - base: PromptFragment class and compose() utility
"""
from app.prompts.base import PromptFragment, compose
from app.prompts import memory, modes

__all__ = [
    # Base utilities
    "PromptFragment",
    "compose",
    # Prompt modules
    "memory",
    "modes",
]
