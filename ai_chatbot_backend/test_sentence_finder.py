"""
Test script for the new find_sentence_positions function.

This demonstrates how to use the enhanced sentence position finder.
"""

from app.services.sentence_citation_service import SentenceCitationService


def test_find_sentence_positions():
    """Test the find_sentence_positions function with example data."""

    # Example: LLM returns these contexts with start/end words
    contexts = [
        {
            "start": "Learning to use if",
            "end": "is an essential skill",
            "file_uuid": "your-file-uuid-here"
        },
        {
            "start": "The while loop",
            "end": "continues until false",
            "file_uuid": "your-file-uuid-here"
        }
    ]

    # Call the function
    result = SentenceCitationService.find_sentence_positions(contexts)

    # Result structure:
    # {
    #     "file-uuid-1": [
    #         SentenceCitation(
    #             content="Learning to use if and while is an essential skill.",
    #             page_index=0,
    #             bbox=[51, 150, 561, 222],
    #             block_type="text",
    #             confidence=1.0
    #         )
    #     ],
    #     "file-uuid-2": [...]
    # }

    for file_uuid, citations in result.items():
        print(f"\nFile: {file_uuid}")
        for citation in citations:
            print(f"  Page {citation.page_index}: {citation.content[:50]}...")
            print(f"  BBox: {citation.bbox}")
            print(f"  Confidence: {citation.confidence}")
            if citation.bboxes:
                print(f"  Multi-line bboxes: {len(citation.bboxes)} regions")


def test_with_file_uuids():
    """Test with explicit file_uuids parameter."""

    # If you want to search only specific files, pass file_uuids
    contexts = [
        {
            "start": "Python is a",
            "end": "programming language"
        },
        {
            "start": "Functions help us",
            "end": "organize our code"
        }
    ]

    # Specify which files to search
    file_uuids = ["file-uuid-1", "file-uuid-2"]

    result = SentenceCitationService.find_sentence_positions(
        contexts=contexts,
        file_uuids=file_uuids
    )

    print(f"\nFound citations in {len(result)} files")


if __name__ == "__main__":
    print("=" * 60)
    print("Testing find_sentence_positions function")
    print("=" * 60)

    print("\n[Test 1] Basic usage with file_uuid in contexts:")
    test_find_sentence_positions()

    print("\n" + "=" * 60)
    print("\n[Test 2] Using explicit file_uuids parameter:")
    test_with_file_uuids()

    print("\n" + "=" * 60)
    print("\nFunction Usage Summary:")
    print("-" * 60)
    print("""
Usage:
    from app.services.sentence_citation_service import SentenceCitationService

    # Prepare contexts from LLM response
    contexts = [
        {
            "start": "first few words",
            "end": "last few words",
            "file_uuid": "abc-123"  # Optional if file_uuids param provided
        }
    ]

    # Call the function
    result = SentenceCitationService.find_sentence_positions(contexts)

    # Or restrict to specific files:
    result = SentenceCitationService.find_sentence_positions(
        contexts=contexts,
        file_uuids=["abc-123", "def-456"]
    )

Features:
    ✓ Batch database queries (efficient for multiple files)
    ✓ Fuzzy matching with confidence scores
    ✓ Only processes PDF files (with sentence_mapping)
    ✓ Returns bbox, page_index, block_type for each citation
    ✓ Handles multi-line sentences (multiple bboxes)
    ✓ Gracefully skips non-PDF files
    """)
