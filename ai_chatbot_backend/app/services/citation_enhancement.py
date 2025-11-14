"""
Citation Enhancement Service

Enhances LLM-generated citations with file metadata and sentence-level positions.
Maps reference numbers to file_uuid and retrieves bbox/page_index information.
"""

from typing import List, Dict, Any, Optional
from app.services.sentence_citation_service import SentenceCitationService
from app.schemas.citations import EnhancedReference, SentenceCitation


def enhance_citations_with_metadata(
    mentioned_contexts: List[Dict[str, Any]],
    reference_list: List[List[Any]]
) -> List[EnhancedReference]:
    """
    Map LLM citations to file metadata and sentence positions.

    This function bridges the gap between LLM's cited references (with start/end words)
    and the actual document metadata (file_uuid, page_index, bbox coordinates).

    Args:
        mentioned_contexts: List of citation dicts from LLM with keys:
            - 'reference': Reference number (1, 2, 3, ...)
            - 'start': First 5-8 words of cited passage
            - 'end': Last 5-8 words of cited passage

        reference_list: List of reference metadata from RAG retrieval:
            [[topic_path, url, file_path, file_uuid, chunk_index], ...]
            Indexed by reference number (0-indexed, so reference 1 = index 0)

    Returns:
        List of EnhancedReference objects containing:
            - Original reference metadata (topic_path, url, file_path, file_uuid, chunk_index)
            - sentences: List of SentenceCitation objects with:
                - content: Full sentence text
                - page_index: 0-indexed page number
                - bbox: Bounding box coordinates [x1, y1, x2, y2]
                - block_type: Type of text block (title, text, etc.)
                - confidence: Match confidence score (0.0-1.0)

    Example:
        >>> mentioned_contexts = [
        ...     {"reference": 1, "start": "The while loop", "end": "until false"},
        ...     {"reference": 1, "start": "Iteration allows", "end": "multiple times"},
        ...     {"reference": 2, "start": "Functions are", "end": "reusable code"}
        ... ]
        >>> reference_list = [
        ...     ["CS61A > Week1", "url1", "path1", "uuid-1", 5],
        ...     ["CS61A > Week2", "url2", "path2", "uuid-2", 3]
        ... ]
        >>> enhanced = enhance_citations_with_metadata(mentioned_contexts, reference_list)
        >>> # Returns 2 EnhancedReference objects (one per unique file_uuid)
        >>> # Each with sentences list containing bbox + page_index
    """

    if not mentioned_contexts or not reference_list:
        return []

    # Group contexts by reference number
    contexts_by_ref = {}
    for ctx in mentioned_contexts:
        ref_num = ctx.get("reference")
        if ref_num is None:
            print(f"[WARNING] Context missing 'reference' field: {ctx}")
            continue

        if ref_num not in contexts_by_ref:
            contexts_by_ref[ref_num] = []

        contexts_by_ref[ref_num].append({
            "start": ctx.get("start", ""),
            "end": ctx.get("end", "")
        })

    # Build enhanced references
    enhanced_refs = []

    for ref_num, contexts in contexts_by_ref.items():
        # Validate reference number
        if ref_num < 1 or ref_num > len(reference_list):
            print(f"[WARNING] Invalid reference number {ref_num} (valid range: 1-{len(reference_list)})")
            continue

        # Get reference metadata (0-indexed)
        ref_data = reference_list[ref_num - 1]

        if len(ref_data) < 5:
            print(f"[WARNING] Invalid reference data format for reference {ref_num}: {ref_data}")
            continue

        topic_path, url, file_path, file_uuid, chunk_index = ref_data

        # Add file_uuid to each context
        contexts_with_uuid = [
            {
                "start": ctx["start"],
                "end": ctx["end"],
                "file_uuid": file_uuid
            }
            for ctx in contexts
            if ctx.get("start") and ctx.get("end")
        ]

        if not contexts_with_uuid:
            print(f"[WARNING] No valid contexts for reference {ref_num}")
            continue

        # Find sentence positions using SentenceCitationService
        # Returns: Dict[file_uuid -> List[SentenceCitation]]
        try:
            sentence_citations_dict = SentenceCitationService.find_sentence_positions(
                contexts_with_uuid
            )

            # Get citations for this specific file
            sentences = sentence_citations_dict.get(file_uuid, [])

            # Create enhanced reference
            enhanced_ref = EnhancedReference(
                topic_path=topic_path,
                url=url if url else None,
                file_path=file_path,
                file_uuid=file_uuid,
                chunk_index=chunk_index,
                sentences=sentences if sentences else None
            )

            enhanced_refs.append(enhanced_ref)

        except Exception as e:
            print(f"[ERROR] Failed to enhance citations for reference {ref_num}: {e}")
            # Still create reference without sentence details
            enhanced_refs.append(EnhancedReference(
                topic_path=topic_path,
                url=url if url else None,
                file_path=file_path,
                file_uuid=file_uuid,
                chunk_index=chunk_index,
                sentences=None
            ))

    return enhanced_refs


def group_citations_by_file(
    enhanced_refs: List[EnhancedReference]
) -> Dict[str, EnhancedReference]:
    """
    Group enhanced references by file_uuid.

    If multiple references point to the same file (e.g., different chunks),
    merge their sentence citations.

    Args:
        enhanced_refs: List of EnhancedReference objects

    Returns:
        Dict mapping file_uuid -> merged EnhancedReference
    """
    file_map = {}

    for ref in enhanced_refs:
        file_uuid = ref.file_uuid

        if file_uuid not in file_map:
            file_map[file_uuid] = ref
        else:
            # Merge sentences
            existing = file_map[file_uuid]
            if ref.sentences:
                if existing.sentences:
                    existing.sentences.extend(ref.sentences)
                else:
                    existing.sentences = ref.sentences

    return file_map


def parse_llm_citation_response(response_text: str) -> tuple[str, List[Dict[str, Any]]]:
    """
    Parse structured JSON response from LLM.

    Extracts answer text and mentioned_contexts array from LLM's JSON response.

    Args:
        response_text: Full LLM response (may contain JSON in code blocks)

    Returns:
        Tuple of (answer_text, mentioned_contexts)
        mentioned_contexts = [
            {"reference": 1, "start": "...", "end": "..."},
            {"reference": 2, "start": "...", "end": "..."}
        ]

    Example:
        >>> response = '{"answer": "While loops...", "mentioned_contexts": [...]}'
        >>> answer, contexts = parse_llm_citation_response(response)
        >>> answer
        'While loops...'
        >>> contexts[0]
        {'reference': 1, 'start': 'The while loop', 'end': 'until false'}
    """
    parsed = SentenceCitationService.parse_structured_response(response_text)
    return parsed.get("answer", response_text), parsed.get("mentioned_contexts", [])
