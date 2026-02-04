"""
Export all prompt combinations for verification.

Generates 8 files representing all combinations of:
- 4 modes (text_chat_tutor, text_chat_regular, voice_tutor, voice_regular)
- 2 scenarios (with_refs, no_refs)

Usage:
    cd ai_chatbot_backend
    python -m app.prompts.scripts.export_prompts
"""

from pathlib import Path

from app.prompts.modes import get_complete_system_prompt


# Output directory (relative to this script's location)
EXPORTS_DIR = Path(__file__).parent.parent / "exports"

# All 8 combinations to export
COMBINATIONS = [
    # (tutor_mode, audio_response, has_refs, filename)
    (True, False, True, "text_chat_tutor_with_refs.txt"),
    (True, False, False, "text_chat_tutor_no_refs.txt"),
    (False, False, True, "text_chat_regular_with_refs.txt"),
    (False, False, False, "text_chat_regular_no_refs.txt"),
    (True, True, True, "voice_tutor_with_refs.txt"),
    (True, True, False, "voice_tutor_no_refs.txt"),
    (False, True, True, "voice_regular_with_refs.txt"),
    (False, True, False, "voice_regular_no_refs.txt"),
]


def export_all_prompts() -> None:
    """Generate and save all 8 prompt combinations."""
    EXPORTS_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Exporting prompts to: {EXPORTS_DIR}")
    print("-" * 50)

    for tutor_mode, audio_response, has_refs, filename in COMBINATIONS:
        # Generate the complete prompt
        prompt = get_complete_system_prompt(
            tutor_mode=tutor_mode,
            audio_response=audio_response,
            has_refs=has_refs,
            course="EXAMPLE_COURSE",
            class_name="Example Class",
        )

        # Save to file
        output_path = EXPORTS_DIR / filename
        output_path.write_text(prompt, encoding="utf-8")

        # Report
        mode_name = "voice" if audio_response else "text_chat"
        mode_type = "tutor" if tutor_mode else "regular"
        refs_status = "with_refs" if has_refs else "no_refs"
        print(f"  {filename}: {len(prompt):,} chars")

    print("-" * 50)
    print(f"Done! Generated {len(COMBINATIONS)} files.")


if __name__ == "__main__":
    export_all_prompts()
