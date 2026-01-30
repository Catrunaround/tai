"""
Composable Prompt Management System for TAI.

This module provides reusable prompt fragments that can be combined
dynamically at runtime to build final prompts for different modes.

Usage:
    from app.prompts import shared, voice, chat, rag, memory
    from app.prompts.base import compose

    # Voice mode: combine shared + voice-specific prompts
    voice_system_prompt = compose(
        shared.TAI_IDENTITY,
        shared.TUTOR_GUIDANCE,
        voice.SPEECH_FRIENDLY_STYLE,
        voice.SPEAKABLE_REFERENCES,
    )

    # Chat mode (JSON): combine shared + chat-specific prompts
    chat_system_prompt = compose(
        shared.TAI_IDENTITY,
        shared.TUTOR_GUIDANCE,
        *chat.get_format_prompts(use_structured_json=True),
    )

Prompt Categories:
    - shared: TAI identity, tutor guidance, off-topic handling (all modes)
    - voice: Speech-friendly style, speakable references (voice mode only)
    - chat: JSON/Markdown formats, citation rules (chat modes)
    - rag: Query reformulation, reference handling (RAG queries)
    - memory: Synopsis compression, merge prompts (memory service)
"""
from app.prompts.base import PromptFragment, compose
from app.prompts import shared, voice, chat, rag, memory

__all__ = [
    # Base utilities
    "PromptFragment",
    "compose",
    # Prompt modules
    "shared",
    "voice",
    "chat",
    "rag",
    "memory",
]
