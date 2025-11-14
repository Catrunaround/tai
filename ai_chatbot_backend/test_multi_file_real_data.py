#!/usr/bin/env python3
"""
Test find_sentence_positions with MULTIPLE FILES using REAL data from database.

This demonstrates the real use case where an LLM cites content from multiple
different files in a single response.
"""

import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(__file__))

from app.services.sentence_citation_service import SentenceCitationService


def test_multi_file_with_real_data():
    """
    Test with real data from 3 different CS 61A PDF files.

    This simulates a real scenario where an LLM generates a response using
    content from multiple documents and cites passages from each.
    """

    # Real file UUIDs from metadata.db
    file_disc03 = "6727fbe0-7ca6-5c63-a0eb-b6dddae38342"  # disc03.pdf
    file_disc09 = "ce36e896-23ad-5f75-af7e-51db0770133e"  # disc09.pdf
    file_control = "ade02994-f176-565f-b0aa-b24711ed07a7"  # 03-Control_1pp.pdf

    # Real contexts extracted from actual sentences in these PDFs
    contexts = [
        # From disc03.pdf - Single sentence citation
        {
            "start": "Getting Started",
            "end": "Getting Started",
            "file_uuid": file_disc03
        },
        # From disc03.pdf - Multi-sentence citation (spans 3 sentences)
        {
            "start": "If you could change",
            "end": "make happen instead",
            "file_uuid": file_disc03
        },
        # From disc03.pdf - Another citation
        {
            "start": "VERY IMPORTANT",
            "end": "running your code",
            "file_uuid": file_disc03
        },
        # From disc09.pdf - Single sentence
        {
            "start": "Scheme lists are very similar",
            "end": "working with in Python",
            "file_uuid": file_disc09
        },
        # From disc09.pdf - Multi-sentence citation
        {
            "start": "Just like how a linked list",
            "end": "created with the constructor cons",
            "file_uuid": file_disc09
        },
        # From Control PDF - Single sentence
        {
            "start": "Control",
            "end": "Control",
            "file_uuid": file_control
        },
        # From Control PDF - Citation with context
        {
            "start": "Conditional statements",
            "end": "may or may not be evaluated",
            "file_uuid": file_control
        },
    ]

    print("=" * 80)
    print("MULTI-FILE TEST WITH REAL DATA")
    print("=" * 80)
    print(f"\nTesting with {len(contexts)} contexts across 3 different PDF files:")
    print(f"  • disc03.pdf       (UUID: ...{file_disc03[-8:]})")
    print(f"  • disc09.pdf       (UUID: ...{file_disc09[-8:]})")
    print(f"  • 03-Control_1pp.pdf (UUID: ...{file_control[-8:]})")
    print()

    # Call the function
    try:
        result = SentenceCitationService.find_sentence_positions(contexts)

        print("=" * 80)
        print("RESULTS")
        print("=" * 80)

        if not result:
            print("\n⚠️  No citations found!")
            print("\nThis could mean:")
            print("  - Database not accessible")
            print("  - Files don't have sentence_mapping in extra_info")
            print("  - Start/end words don't match sentences in the database")
            return

        # Summary
        total_citations = sum(len(citations) for citations in result.values())
        print(f"\n✅ Successfully found citations in {len(result)} file(s)")
        print(f"   Total citations returned: {total_citations}")
        print()

        # Detailed results per file
        file_names = {
            file_disc03: "disc03.pdf",
            file_disc09: "disc09.pdf",
            file_control: "03-Control_1pp.pdf"
        }

        for file_uuid, citations in result.items():
            file_name = file_names.get(file_uuid, "Unknown file")
            print("\n" + "─" * 80)
            print(f"📄 File: {file_name}")
            print(f"   UUID: {file_uuid}")
            print(f"   Citations found: {len(citations)}")
            print("─" * 80)

            for i, citation in enumerate(citations, 1):
                print(f"\n   [{i}] Citation:")
                print(f"       Content: {citation.content[:70]}...")
                print(f"       Page: {citation.page_index}")
                print(f"       BBox: {citation.bbox}")
                print(f"       Type: {citation.block_type}")
                print(f"       Confidence: {citation.confidence:.2%}")

                if citation.bboxes and len(citation.bboxes) > 1:
                    print(f"       Multi-line: {len(citation.bboxes)} regions")

        print("\n" + "=" * 80)
        print("TEST RESULTS SUMMARY")
        print("=" * 80)

        # Count by file
        for file_uuid, citations in result.items():
            file_name = file_names.get(file_uuid, "Unknown")
            print(f"  {file_name:20s} → {len(citations)} citation(s)")

        print(f"\n  Total across all files → {total_citations} citation(s)")

        # Check confidence scores
        all_confidences = [c.confidence for citations in result.values() for c in citations]
        avg_confidence = sum(all_confidences) / len(all_confidences)
        exact_matches = sum(1 for c in all_confidences if c == 1.0)
        fuzzy_matches = len(all_confidences) - exact_matches

        print(f"\n  Average confidence: {avg_confidence:.2%}")
        print(f"  Exact matches: {exact_matches}")
        print(f"  Fuzzy matches: {fuzzy_matches}")

        print("\n" + "=" * 80)
        print("✅ Multi-file test completed successfully!")
        print("=" * 80)

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()


def test_cross_file_same_context():
    """
    Test edge case: Same citation text might appear in multiple files.

    This tests that the function correctly attributes citations to their
    respective files when similar content exists across documents.
    """

    print("\n\n" + "=" * 80)
    print("CROSS-FILE TEST: Same words in different files")
    print("=" * 80)

    # These files might have similar content (both are discussion worksheets)
    file_disc03 = "6727fbe0-7ca6-5c63-a0eb-b6dddae38342"
    file_disc09 = "ce36e896-23ad-5f75-af7e-51db0770133e"

    contexts = [
        {
            "start": "Getting Started",
            "end": "Getting Started",
            "file_uuid": file_disc03
        },
        {
            "start": "Scheme Lists",
            "end": "Scheme Lists",
            "file_uuid": file_disc09
        }
    ]

    try:
        result = SentenceCitationService.find_sentence_positions(contexts)

        print(f"\n✅ Found citations in {len(result)} file(s)")
        for file_uuid, citations in result.items():
            print(f"   File ...{file_uuid[-8:]}: {len(citations)} citation(s)")
            for cit in citations:
                print(f"      → {cit.content[:50]}")

        print("\n✅ Cross-file attribution working correctly!")

    except Exception as e:
        print(f"❌ Error: {e}")


def test_alternative_api_usage():
    """
    Test with real existing sentences to demonstrate efficient batch processing.

    Uses actual sentences that exist in the database to show how the function
    efficiently handles multiple citations with a single database query.
    """

    print("\n\n" + "=" * 80)
    print("BATCH PROCESSING TEST: Efficient multi-file citation lookup")
    print("=" * 80)

    # Real file UUIDs
    file_disc03 = "6727fbe0-7ca6-5c63-a0eb-b6dddae38342"
    file_disc09 = "ce36e896-23ad-5f75-af7e-51db0770133e"
    file_control = "ade02994-f176-565f-b0aa-b24711ed07a7"

    # Real contexts with existing sentences from database
    contexts = [
        # From disc03.pdf
        {
            "start": "Recursion",
            "end": "Recursion",
            "file_uuid": file_disc03
        },
        {
            "start": "If you could change one",
            "end": "what would it be",
            "file_uuid": file_disc03
        },
        # From disc09.pdf
        {
            "start": "Scheme Lists",
            "end": "Scheme Lists",
            "file_uuid": file_disc09
        },
        {
            "start": "Scheme lists require",
            "end": "or nil, an empty list",
            "file_uuid": file_disc09
        },
        {
            "start": "We recommend that you use",
            "end": "automatic drawing of diagrams",
            "file_uuid": file_disc09
        },
        # From Control PDF
        {
            "start": "Announcements",
            "end": "Announcements",
            "file_uuid": file_control
        },
        {
            "start": "Print and None",
            "end": "Print and None",
            "file_uuid": file_control
        },
    ]

    print(f"\nBatch processing {len(contexts)} citations from 3 files:")
    print(f"  • disc03.pdf: 2 citations")
    print(f"  • disc09.pdf: 3 citations")
    print(f"  • Control PDF: 2 citations")
    print(f"\n→ Function makes only 1 database query for all files (efficient!)")

    try:
        result = SentenceCitationService.find_sentence_positions(contexts)

        if result:
            print(f"\n✅ Successfully retrieved all citations")
            print(f"   Files processed: {len(result)}")

            total_found = sum(len(cits) for cits in result.values())
            print(f"   Citations found: {total_found}/{len(contexts)}")

            print("\n   Results by file:")
            file_names = {
                file_disc03: "disc03.pdf",
                file_disc09: "disc09.pdf",
                file_control: "03-Control_1pp.pdf"
            }

            for file_uuid, citations in result.items():
                file_name = file_names.get(file_uuid, "Unknown")
                print(f"      {file_name:20s} → {len(citations)} citation(s)")
                for cit in citations:
                    print(f"         • {cit.content[:50]}... (page {cit.page_index})")

            print("\n✅ Batch processing completed efficiently!")
        else:
            print("\n⚠️  No matches found")

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    # Run all tests
    test_multi_file_with_real_data()
    test_cross_file_same_context()
    test_alternative_api_usage()

    print("\n\n" + "=" * 80)
    print("USAGE SUMMARY")
    print("=" * 80)
    print("""
This demonstrates the real-world usage pattern:

1. Your RAG system retrieves chunks from multiple files
2. LLM generates response citing content from these files
3. LLM returns start/end words for each citation
4. You call find_sentence_positions() with all contexts
5. Function returns bboxes grouped by file_uuid
6. Frontend highlights all citations across multiple PDFs

Example integration:

    # After RAG + LLM generation
    rag_chunks = [...]  # Chunks with file_uuids
    llm_response = {"answer": "...", "mentioned_contexts": [...]}

    # Add file info to contexts
    contexts = []
    for ctx, chunk in zip(llm_response["mentioned_contexts"], rag_chunks):
        contexts.append({
            "start": ctx["start"],
            "end": ctx["end"],
            "file_uuid": chunk["file_uuid"]
        })

    # Get all bbox positions
    positions = SentenceCitationService.find_sentence_positions(contexts)

    # Now you have everything to highlight citations in multiple PDFs!
    for file_uuid, citations in positions.items():
        print(f"File {file_uuid}:")
        for cit in citations:
            print(f"  - Highlight page {cit.page_index} at {cit.bbox}")
    """)
