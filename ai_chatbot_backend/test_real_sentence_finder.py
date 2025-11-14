#!/usr/bin/env python3
"""
Real test of find_sentence_positions with actual database.
"""

import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(__file__))

from app.services.sentence_citation_service import SentenceCitationService


def test_with_real_database():

    # Real file UUID from test database
    file_uuid = "52318607-b3c5-5132-ae1b-9342fc22a6ea"

    # Test contexts based on actual sentences in the database
    contexts = [
        {
            "start": "False values in Python",
            "end": "expression evaluates to v.",
            "file_uuid": file_uuid
        },
        {
            "start": "A pure function's behavior is",
            "end": "but execute it many times",
            "file_uuid": file_uuid
        },
        {
            "start": "Two players alternate turns",
            "end": "add to the total loses",
            "file_uuid": file_uuid
        }
    ]

    print("=" * 70)
    print("Testing find_sentence_positions with real database")
    print("=" * 70)
    print(f"\nFile UUID: {file_uuid}")
    print(f"Number of contexts to find: {len(contexts)}")
    print("\nSearching for:")
    for i, ctx in enumerate(contexts, 1):
        print(f"  {i}. Start: '{ctx['start'][:30]}...'")
        print(f"     End: '{ctx['end'][:30]}...'")

    # Call the function
    try:
        result = SentenceCitationService.find_sentence_positions(contexts)

        print("\n" + "=" * 70)
        print("RESULTS")
        print("=" * 70)

        if not result:
            print("\n⚠️  No citations found!")
            print("\nPossible reasons:")
            print("  - Database not found or empty")
            print("  - File UUID not in database")
            print("  - No sentence_mapping in extra_info")
            print("  - Start/end words don't match any sentences")
            return

        for file_uuid, citations in result.items():
            print(f"\n📄 File: {file_uuid}")
            print(f"   Found {len(citations)} citation(s)\n")

            for i, citation in enumerate(citations, 1):
                print(f"   Citation #{i}:")
                print(f"      Content: {citation.content[:80]}...")
                print(f"      Page: {citation.page_index}")
                print(f"      BBox: {citation.bbox}")
                print(f"      Block Type: {citation.block_type}")
                print(f"      Confidence: {citation.confidence:.2f}")
                if citation.bboxes and len(citation.bboxes) > 1:
                    print(f"      Multi-line: {len(citation.bboxes)} regions")
                print()

        print("=" * 70)
        print("✅ Test completed successfully!")
        print("=" * 70)

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()


def test_fuzzy_matching():
    """Test fuzzy matching with slightly different text"""

    file_uuid = "52318607-b3c5-5132-ae1b-9342fc22a6ea"

    # These have slight variations
    contexts = [
        {
            "start": "learning to use if",  # lowercase
            "end": "essential skill.",      # with period
            "file_uuid": file_uuid
        }
    ]

    print("\n" + "=" * 70)
    print("Testing fuzzy matching (text with variations)")
    print("=" * 70)

    try:
        result = SentenceCitationService.find_sentence_positions(contexts)

        if result:
            for file_uuid, citations in result.items():
                print(f"\n✅ Fuzzy match succeeded!")
                for citation in citations:
                    print(f"   Confidence: {citation.confidence:.2f}")
                    print(f"   Found: {citation.content[:60]}...")
        else:
            print("\n⚠️  Fuzzy match did not find results")

    except Exception as e:
        print(f"\n❌ Error: {e}")


if __name__ == "__main__":
    # Set database path for testing
    os.environ.setdefault('METADATA_DB_PATH',
                         '../rag/file_conversion_router/tests/disc01/test_metadata.db')

    test_with_real_database()
    test_fuzzy_matching()

    print("\n" + "=" * 70)
    print("API Usage Example:")
    print("=" * 70)
    print("""
    from app.services.sentence_citation_service import SentenceCitationService

    # Your LLM returns these contexts
    contexts = [
        {
            "start": "first few words from reference",
            "end": "last few words from reference",
            file_uuid = "52318607-b3c5-5132-ae1b-9342fc22a6ea"
        }
    ]

    # Find the positions
    result = SentenceCitationService.find_sentence_positions(contexts)

    # result = {
    #     "abc-123-def": [
    #         SentenceCitation(
    #             content="full sentence text...",
    #             page_index=0,
    #             bbox=[x1, y1, x2, y2],
    #             block_type="text",
    #             confidence=1.0
    #         )
    #     ]
    # }

    # Use the bboxes for PDF highlighting
    for file_uuid, citations in result.items():
        for citation in citations:
            print(f"Highlight page {citation.page_index} at {citation.bbox}")
    """)
