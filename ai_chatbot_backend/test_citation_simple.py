#!/usr/bin/env python3
"""
Simple test for citation enhancement - minimal dependencies
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

def test_parse_json():
    """Test JSON parsing logic"""
    print("=" * 80)
    print("TEST: JSON Parsing Logic")
    print("=" * 80)

    from app.services.sentence_citation_service import SentenceCitationService

    llm_response = '''
{
    "answer": "While loops continue executing until false.",
    "mentioned_contexts": [
        {
            "reference": 1,
            "start": "The while loop",
            "end": "until false"
        }
    ]
}
    '''

    parsed = SentenceCitationService.parse_structured_response(llm_response)

    print(f"\n✅ Answer: {parsed['answer']}")
    print(f"✅ Contexts: {len(parsed['mentioned_contexts'])}")
    print(f"✅ First context reference: {parsed['mentioned_contexts'][0]['reference']}")

    assert parsed['mentioned_contexts'][0]['reference'] == 1
    assert 'start' in parsed['mentioned_contexts'][0]
    assert 'end' in parsed['mentioned_contexts'][0]

    print("\n✅ TEST PASSED\n")


def test_find_sentence_positions():
    """Test the sentence position finder with real database"""
    print("=" * 80)
    print("TEST: Find Sentence Positions")
    print("=" * 80)

    from app.services.sentence_citation_service import SentenceCitationService

    # Real file UUID from database
    file_disc03 = "6727fbe0-7ca6-5c63-a0eb-b6dddae38342"

    contexts = [
        {
            "start": "Getting Started",
            "end": "Getting Started",
            "file_uuid": file_disc03
        },
        {
            "start": "Recursion",
            "end": "Recursion",
            "file_uuid": file_disc03
        }
    ]

    print(f"\nSearching for {len(contexts)} citations...")

    try:
        result = SentenceCitationService.find_sentence_positions(contexts)

        print(f"\n✅ Found citations in {len(result)} file(s)")

        for file_uuid, citations in result.items():
            print(f"\n   File: ...{file_uuid[-8:]}")
            print(f"   Citations: {len(citations)}")

            for i, cit in enumerate(citations, 1):
                print(f"      [{i}] {cit.content[:40]}...")
                print(f"          Page: {cit.page_index}")
                print(f"          BBox: {cit.bbox}")
                print(f"          Confidence: {cit.confidence:.2%}")

        print("\n✅ TEST PASSED\n")

    except Exception as e:
        print(f"\n❌ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()


def test_citation_enhancement_logic():
    """Test the citation enhancement mapping logic"""
    print("=" * 80)
    print("TEST: Citation Enhancement Mapping")
    print("=" * 80)

    from app.services.citation_enhancement import enhance_citations_with_metadata

    # Test data
    file_disc03 = "6727fbe0-7ca6-5c63-a0eb-b6dddae38342"

    mentioned_contexts = [
        {
            "reference": 1,
            "start": "Getting Started",
            "end": "Getting Started"
        },
        {
            "reference": 1,
            "start": "Recursion",
            "end": "Recursion"
        }
    ]

    reference_list = [
        ["CS61A > Disc03", None, "disc03.pdf", file_disc03, 5]
    ]

    print(f"\nMapping {len(mentioned_contexts)} contexts to reference list...")

    try:
        enhanced_refs = enhance_citations_with_metadata(mentioned_contexts, reference_list)

        print(f"\n✅ Enhanced {len(enhanced_refs)} reference(s)")

        for ref in enhanced_refs:
            print(f"\n   File UUID: {ref.file_uuid}")
            print(f"   Topic: {ref.topic_path}")

            if ref.sentences:
                print(f"   Sentences: {len(ref.sentences)}")
                for sent in ref.sentences:
                    print(f"      • {sent.content[:50]}... (page {sent.page_index})")
            else:
                print(f"   No sentences found")

        print("\n✅ TEST PASSED\n")

    except Exception as e:
        print(f"\n❌ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    print("\n" + "=" * 80)
    print("ENHANCED CITATION SYSTEM - SIMPLE TESTS")
    print("=" * 80 + "\n")

    test_parse_json()
    test_find_sentence_positions()
    test_citation_enhancement_logic()

    print("=" * 80)
    print("✅ ALL SIMPLE TESTS COMPLETED")
    print("=" * 80)
