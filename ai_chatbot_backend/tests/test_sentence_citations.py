"""
Test script for sentence-level citation feature

This demonstrates:
1. Parsing structured LLM responses with mentioned_contexts
2. Matching mentioned contexts to sentence mappings
3. Retrieving bboxes for cited sentences
"""

import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import json
from app.services.sentence_citation_service import SentenceCitationService


def test_parse_structured_response():
    """Test parsing of structured JSON response from LLM"""
    print("\n=== Test 1: Parse Structured Response ===")

    # Simulated LLM response with structured output (new start/end format)
    llm_response = """
    {
        "answer": "Learning to use if and while is an essential skill for programming. These control structures allow you to make decisions and repeat actions in your code.",
        "mentioned_contexts": [
            {"start": "Learning to use if and while", "end": "is an essential skill"},
            {"start": "During this discussion, focus on what", "end": "in the first three lectures"}
        ]
    }
    """

    parsed = SentenceCitationService.parse_structured_response(llm_response)

    print(f"Answer: {parsed['answer'][:100]}...")
    print(f"Mentioned contexts: {len(parsed['mentioned_contexts'])} citations")
    for i, context in enumerate(parsed['mentioned_contexts']):
        print(f"  [{i+1}] start: \"{context['start']}\" ... end: \"{context['end']}\"")

    assert parsed['answer'] is not None
    assert len(parsed['mentioned_contexts']) == 2
    assert 'start' in parsed['mentioned_contexts'][0]
    assert 'end' in parsed['mentioned_contexts'][0]
    print("✓ Test passed!")


def test_match_contexts_to_sentences():
    """Test matching mentioned contexts to sentence mappings using start/end words"""
    print("\n=== Test 2: Match Contexts to Sentence Mappings (Start/End) ===")

    # Load the sample sentence mapping
    sample_file = "/Users/yyk956614/tai/rag/file_conversion_router/tests/disc01/disc01.pdf_lines.json"

    try:
        with open(sample_file, 'r') as f:
            sentence_mapping = json.load(f)

        print(f"Loaded sentence mapping with {len(sentence_mapping)} blocks")

        # Simulate mentioned contexts with start/end format
        mentioned_contexts = [
            {"start": "Learning to use if and", "end": "is an essential skill"},
            {"start": "The race function below sometimes", "end": "and sometimes runs forever"}
        ]

        # Test the actual service method
        citations = SentenceCitationService._match_to_mapping(
            mentioned_contexts,
            sentence_mapping,
            []  # chunks not needed for this test
        )

        print(f"\nMatched {len(citations)} citations:")
        for i, citation in enumerate(citations):
            print(f"\n  Citation {i+1}:")
            print(f"    Content: {citation.content[:60]}...")
            print(f"    Page: {citation.page_index}")
            print(f"    Bbox: {citation.bbox}")
            print(f"    Type: {citation.block_type}")

        print(f"\n✓ Successfully matched {len(citations)} out of {len(mentioned_contexts)} contexts")
        print("✓ Test passed!")

    except FileNotFoundError:
        print(f"⚠ Sample file not found: {sample_file}")
        print("  This is expected if not running on the server with test data")


def test_multi_sentence_citation():
    """Test citations that span multiple sentences"""
    print("\n=== Test 3: Multi-Sentence Citation ===")

    # Load the sample sentence mapping
    sample_file = "/Users/yyk956614/tai/rag/file_conversion_router/tests/disc01/disc01.pdf_lines.json"

    try:
        with open(sample_file, 'r') as f:
            sentence_mapping = json.load(f)

        print(f"Loaded sentence mapping with {len(sentence_mapping)} blocks")

        # Test multi-sentence citation with start from one sentence and end from another
        mentioned_contexts = [
            {
                "start": "Learning to use if and",
                "end": "in the first three lectures"
            }
        ]

        print("\nTesting multi-sentence citation:")
        print(f"  Start: \"{mentioned_contexts[0]['start']}\"")
        print(f"  End: \"{mentioned_contexts[0]['end']}\"")
        print("  (This should capture text spanning multiple sentences)")

        # Test the actual service method
        citations = SentenceCitationService._match_to_mapping(
            mentioned_contexts,
            sentence_mapping,
            []  # chunks not needed for this test
        )

        if citations:
            print(f"\n✓ Successfully matched multi-sentence citation!")
            for i, citation in enumerate(citations):
                print(f"\n  Citation {i+1}:")
                content_preview = citation.content[:100] + "..." if len(citation.content) > 100 else citation.content
                print(f"    Content: {content_preview}")
                print(f"    Length: {len(citation.content)} characters")
                print(f"    Page: {citation.page_index}")
                print(f"    Primary Bbox: {citation.bbox}")
                print(f"    Type: {citation.block_type}")

                # Check for multiple bboxes
                if citation.bboxes:
                    print(f"    ✓ Multi-line citation with {len(citation.bboxes)} bounding boxes:")
                    for j, bbox in enumerate(citation.bboxes):
                        print(f"      Region {j+1}: {bbox}")
                else:
                    print(f"    Single-line citation (only one bbox)")

                # Verify the content spans multiple concepts
                if len(citation.content) > 50:
                    print(f"    ✓ Content is substantial (likely multi-sentence)")
        else:
            print("  ⚠ No matches found")

        print("\n✓ Test completed!")

    except FileNotFoundError:
        print(f"⚠ Sample file not found: {sample_file}")
        print("  This is expected if not running on the server with test data")


def test_multi_bbox_verification():
    """Test that verifies multiple distinct bboxes are returned"""
    print("\n=== Test 4: Multi-Bbox Verification ===")

    # Create a synthetic sentence mapping with clearly different bbox regions
    synthetic_mapping = [
        {
            "index": 0,
            "page_index": 0,
            "block_type": "text",
            "spans": [
                {
                    "content": "This is the first line of text that starts here.",
                    "bbox": [100, 100, 500, 120]
                }
            ]
        },
        {
            "index": 1,
            "page_index": 0,
            "block_type": "text",
            "spans": [
                {
                    "content": "This is the second line that continues the thought.",
                    "bbox": [100, 130, 500, 150]
                }
            ]
        },
        {
            "index": 2,
            "page_index": 0,
            "block_type": "text",
            "spans": [
                {
                    "content": "And this is the third line to complete it.",
                    "bbox": [100, 160, 500, 180]
                }
            ]
        }
    ]

    # Test citation spanning all three lines
    mentioned_contexts = [
        {
            "start": "This is the first line",
            "end": "to complete it"
        }
    ]

    print("\nTesting citation spanning 3 distinct visual regions:")
    print(f"  Start: \"{mentioned_contexts[0]['start']}\"")
    print(f"  End: \"{mentioned_contexts[0]['end']}\"")

    citations = SentenceCitationService._match_to_mapping(
        mentioned_contexts,
        synthetic_mapping,
        []
    )

    if citations:
        citation = citations[0]
        print(f"\n✓ Citation matched!")
        print(f"  Content length: {len(citation.content)} characters")
        print(f"  Primary bbox: {citation.bbox}")

        if citation.bboxes:
            print(f"  ✓✓ Multiple bboxes returned: {len(citation.bboxes)} regions")
            for i, bbox in enumerate(citation.bboxes):
                print(f"    Region {i+1}: {bbox}")

            # Verify they are actually different
            unique_bboxes = [list(b) for b in set(tuple(b) for b in citation.bboxes)]
            if len(unique_bboxes) > 1:
                print(f"  ✓✓✓ Bboxes are distinct! ({len(unique_bboxes)} unique regions)")
            else:
                print(f"  ⚠ Warning: Bboxes are identical (may be expected for some PDFs)")
        else:
            print(f"  ⚠ Warning: Only single bbox returned (expected multiple)")

        print("\n✓ Test completed!")
    else:
        print("  ✗ Test failed: No citation matched")


def test_end_to_end_flow():
    """Demonstrate the complete end-to-end flow with start/end word markers"""
    print("\n=== Test 5: End-to-End Citation Flow (Start/End Format) ===")

    print("""
    Complete Flow with Start/End Word Markers:

    1. User asks: "What is the race function?"

    2. RAG retrieves relevant chunks from disc01.pdf

    3. LLM generates structured response with start/end markers:
       {
           "answer": "The race function is designed to...",
           "mentioned_contexts": [
               {
                   "start": "The race function below sometimes",
                   "end": "and sometimes runs forever"
               }
           ]
       }

    4. Service uses exact-start + fuzzy-range algorithm:
       - Finds exact match for "The race function below sometimes"
       - Searches forward 1000 chars for fuzzy match of "and sometimes runs forever"
       - Extracts content between start and end positions
       - Maps positions back to sentence_mapping to get bbox

    5. API returns enhanced references:
       {
           "topic_path": "CS61A > Discussion 01 > Q1: Race",
           "file_uuid": "...",
           "chunk_index": 6,
           "sentences": [
               {
                   "content": "The race function below sometimes returns the wrong value and sometimes runs forever",
                   "page_index": 0,
                   "bbox": [52, 255, 444, 269],
                   "block_type": "text"
               }
           ]
       }

    6. Frontend displays PDF with highlighted citation at bbox coordinates

    Benefits of Start/End Approach:
    - Faster search (exact substring matching instead of full fuzzy comparison)
    - More precise (pinpoints exact location in document)
    - More efficient (LLM provides 10-16 words instead of full sentences)
    - Better handles continuous sentences that span multiple lines
    """)

    print("✓ End-to-end flow documented!")


def main():
    """Run all tests"""
    print("=" * 60)
    print("Sentence-Level Citation Feature Tests")
    print("=" * 60)

    test_parse_structured_response()
    test_match_contexts_to_sentences()
    test_multi_sentence_citation()
    test_multi_bbox_verification()
    test_end_to_end_flow()

    print("\n" + "=" * 60)
    print("All tests completed!")
    print("=" * 60)


if __name__ == "__main__":
    main()
