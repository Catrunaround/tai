"""
Service for matching mentioned contexts to sentence mappings and extracting bboxes
"""

import json
import re
from typing import List, Dict, Any, Optional
from difflib import SequenceMatcher
from vllm import SamplingParams
from vllm.sampling_params import GuidedDecodingParams
from app.core.dbs.metadata_db import get_metadata_db
from app.core.models.metadata import FileModel
from app.schemas.citations import SentenceCitation

try:
    import jsonschema
    JSONSCHEMA_AVAILABLE = True
except ImportError:
    JSONSCHEMA_AVAILABLE = False
    print("[WARNING] jsonschema not installed. JSON schema validation will be skipped.")


# JSON Schema for citation responses - enforces structured output
# Format: references (with mentioned contexts nested) → answer
CITATION_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "references": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "reference": {
                        "type": "integer",
                        "description": "Reference number from provided references (e.g., 1, 2, 3)"
                    },
                    "mentioned_contexts": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "start": {
                                    "type": "string",
                                    "description": "First 3-5 words from the cited passage (approximate match is fine)"
                                },
                                "end": {
                                    "type": "string",
                                    "description": "Last 3-5 words from the cited passage (approximate match is fine)"
                                }
                            },
                            "required": ["start", "end"],
                            "additionalProperties": False
                        },
                        "description": "Specific parts of this reference that will be used"
                    }
                },
                "required": ["reference", "mentioned_contexts"],
                "additionalProperties": False
            },
            "description": "Array of references with their specific mentioned contexts"
        },
        "answer": {
            "type": "string",
            "description": "The complete answer to the user's question, generated using the pre-selected references"
        }
    },
    "required": ["references", "answer"],
    "additionalProperties": False
}

# Guided decoding parameters for citation responses (VLLM only)
CITATION_GUIDED_DECODING = GuidedDecodingParams(json=CITATION_JSON_SCHEMA)

# Sampling parameters with guided decoding for citations
CITATION_SAMPLING_PARAMS = SamplingParams(
    temperature=0.0,  # Deterministic output for reliable JSON
    top_p=1.0,
    max_tokens=6000,
    guided_decoding=CITATION_GUIDED_DECODING,
    skip_special_tokens=False
)

# Simplified JSON Schema for streaming-friendly format
# Format: {"answer": "text", "mentioned_contexts": [{"reference": 1, "start": "...", "end": "..."}]}
SIMPLE_CITATION_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {
            "type": "string",
            "description": "The complete answer to the user's question"
        },
        "mentioned_contexts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "reference": {
                        "type": "integer",
                        "description": "Reference number (1-indexed) from provided references"
                    },
                    "start": {
                        "type": "string",
                        "description": "First 3-5 words from the cited passage in the reference"
                    },
                    "end": {
                        "type": "string",
                        "description": "Last 3-5 words from the cited passage in the reference"
                    }
                },
                "required": ["reference", "start", "end"],
                "additionalProperties": False
            },
            "description": "Array of references with cited text snippets"
        }
    },
    "required": ["answer", "mentioned_contexts"],
    "additionalProperties": False
}

# Guided decoding for simplified format
SIMPLE_CITATION_GUIDED_DECODING = GuidedDecodingParams(json=SIMPLE_CITATION_JSON_SCHEMA)

# Sampling parameters for simplified streaming format (Qwen3 thinking model compatible)
SIMPLE_CITATION_SAMPLING_PARAMS = SamplingParams(
    temperature=0.0,  # Deterministic for consistent JSON structure
    top_p=1.0,
    max_tokens=6000,
    guided_decoding=SIMPLE_CITATION_GUIDED_DECODING,
    skip_special_tokens=False
)


class SentenceCitationService:
    """Service to match mentioned contexts to sentence mappings with bboxes"""

    @staticmethod
    def find_sentence_positions(
        contexts: List[Dict[str, str]],
        file_uuids: Optional[List[str]] = None
    ) -> Dict[str, List[SentenceCitation]]:

        if not contexts:
            return {}

        # Extract unique file_uuids from contexts or use provided list
        if file_uuids is None:
            # This is the normal path - extract file_uuids from context dicts
            file_uuids = []
            for ctx in contexts:
                if not isinstance(ctx, dict):
                    print(f"[ERROR] Invalid context type: {type(ctx)}, value: {ctx}")
                    continue
                file_uuid = ctx.get("file_uuid")
                if file_uuid:
                    file_uuids.append(file_uuid)
            file_uuids = list(set(file_uuids))
            print(f"[DEBUG] Extracted {len(file_uuids)} file_uuids from {len(contexts)} contexts")

        # Batch fetch sentence mappings for all files
        file_mappings = SentenceCitationService._batch_fetch_sentence_mappings(file_uuids)

        if not file_mappings:
            print("[WARNING] No sentence mappings found for provided file_uuids")
            return {}

        # Group contexts by file_uuid
        contexts_by_file = {}
        for ctx in contexts:
            file_uuid = ctx.get("file_uuid")
            if not file_uuid:
                print(f"[WARNING] Context missing file_uuid: {ctx}")
                continue

            if file_uuid not in file_mappings:
                # This file doesn't have sentence mapping (not a PDF or not processed)
                continue

            if file_uuid not in contexts_by_file:
                contexts_by_file[file_uuid] = []
            contexts_by_file[file_uuid].append(ctx)

        # Match contexts to sentences for each file
        result = {}
        for file_uuid, file_contexts in contexts_by_file.items():
            sentence_mapping = file_mappings[file_uuid]

            # Use fuzzy matching across sentence boundaries (handles multi-sentence citations)
            # This builds full text from all sentences and does fuzzy matching
            citations = SentenceCitationService._match_to_mapping(
                file_contexts,
                sentence_mapping
            )

            if citations:
                result[file_uuid] = citations

        return result

    @staticmethod
    def _batch_fetch_sentence_mappings(file_uuids: List[str]) -> Dict[str, List[Dict[str, Any]]]:
        """
        Batch fetch sentence mappings for multiple files at once.

        Args:
            file_uuids: List of file UUIDs to fetch

        Returns:
            Dict mapping file_uuid -> sentence_mapping (only for files that have mappings)
        """
        if not file_uuids:
            return {}

        result = {}

        # get_metadata_db() is a generator that yields a session
        session_gen = get_metadata_db()
        session = next(session_gen)

        try:
            # Batch query for all files at once
            files = session.query(FileModel).filter(
                FileModel.uuid.in_(file_uuids)
            ).all()

            for file_model in files:
                sentence_mapping = file_model.get_sentence_mapping()
                print(f"[DEBUG] Fetched sentence mapping for file {file_model.uuid}: {bool(sentence_mapping)}")
                if sentence_mapping:
                    result[file_model.uuid] = sentence_mapping

        finally:
            # Close the session properly
            try:
                next(session_gen)
            except StopIteration:
                pass

        return result

    @staticmethod
    def match_contexts_to_sentences(
        mentioned_contexts: List[Dict[str, str]],
        chunks: List[Dict[str, Any]]
    ) -> Dict[str, List[SentenceCitation]]:
        """
        Match mentioned contexts to sentence mappings and extract bboxes.

        Args:
            mentioned_contexts: List of dicts with 'start' and 'end' keys containing
                               the first 5-8 words and last 5-8 words of cited passages
            chunks: List of chunk dicts with keys: {text, file_uuid, chunk_index, ...}

        Returns:
            Dict mapping file_uuid -> list of SentenceCitation objects
        """
        if not mentioned_contexts or not chunks:
            return {}

        # Group chunks by file_uuid
        file_chunks = {}
        for chunk in chunks:
            file_uuid = chunk.get("file_uuid")
            if file_uuid:
                if file_uuid not in file_chunks:
                    file_chunks[file_uuid] = []
                file_chunks[file_uuid].append(chunk)

        # Get sentence mappings for each file
        result = {}
        db = get_metadata_db()

        for file_uuid, file_chunk_list in file_chunks.items():
            with db.get_session() as session:
                file_model = session.query(FileModel).filter(
                    FileModel.uuid == file_uuid
                ).first()

                if not file_model:
                    continue

                sentence_mapping = file_model.get_sentence_mapping()
                if not sentence_mapping:
                    continue

                # Match mentioned contexts to sentences in the mapping
                citations = SentenceCitationService._match_to_mapping(
                    mentioned_contexts,
                    sentence_mapping,
                    file_chunk_list
                )

                if citations:
                    result[file_uuid] = citations

        return result

    @staticmethod
    def _match_to_mapping(
        mentioned_contexts: List[Dict[str, str]],
        sentence_mapping: List[Dict[str, Any]],
        chunks: List[Dict[str, Any]] = None  # Deprecated parameter, kept for backward compatibility
    ) -> List[SentenceCitation]:
        """
        Match mentioned contexts to sentences in the mapping using exact-start + fuzzy-range algorithm.

        Args:
            mentioned_contexts: List of dicts with 'start' and 'end' word markers
            sentence_mapping: Sentence mapping from file.extra_info
            chunks: Chunks from this file (for context)

        Returns:
            List of SentenceCitation objects with bboxes
        """
        citations = []

        # Build a searchable text from sentence mapping with position tracking
        full_text, position_map = SentenceCitationService._build_searchable_text(sentence_mapping)
        full_text_normalized = SentenceCitationService._normalize_text(full_text)

        used_ranges = []  # Track used character ranges to avoid duplicates

        for context in mentioned_contexts:
            start_text = context.get("start", "")
            end_text = context.get("end", "")

            if not start_text or not end_text:
                print(f"[WARNING] Missing start or end in context: {context}")
                continue

            # Normalize start and end texts
            start_normalized = SentenceCitationService._normalize_text(start_text)
            end_normalized = SentenceCitationService._normalize_text(end_text)

            # Track confidence: start with 1.0 (exact match), reduce for fuzzy matches
            match_confidence = 1.0

            # Find exact match for start (try multiple strategies)
            start_pos = full_text_normalized.find(start_normalized)

            if start_pos == -1:
                # Try fuzzy match for start as fallback
                start_pos, start_score = SentenceCitationService._fuzzy_find_start(
                    start_normalized,
                    full_text_normalized,
                    threshold=0.75  # More lenient threshold
                )
                if start_pos == -1:
                    print(f"[WARNING] Could not find start text: '{start_text[:50]}'")
                    print(f"[DEBUG] Normalized start: '{start_normalized}'")
                    print(f"[DEBUG] Full text preview: '{full_text_normalized[:200]}...'")
                    continue
                # Reduce confidence for fuzzy start match
                match_confidence *= start_score
                print(f"[INFO] Fuzzy matched start with confidence {start_score:.2f}")

            # Define search range for end (3000 chars forward from start for longer citations)
            search_range_start = start_pos
            search_range_end = min(start_pos + 3000, len(full_text_normalized))
            search_text = full_text_normalized[search_range_start:search_range_end]

            # Try exact match first for end
            end_pos_in_range = search_text.find(end_normalized)

            if end_pos_in_range != -1:
                # Exact match found
                end_pos = search_range_start + end_pos_in_range + len(end_normalized)
            else:
                # Fuzzy match for end within range
                end_pos, end_score = SentenceCitationService._fuzzy_find_end(
                    end_normalized,
                    search_text,
                    search_range_start,
                    threshold=0.75  # More lenient threshold
                )

                if end_pos == -1:
                    print(f"[WARNING] Could not find end text: '{end_text[:50]}'")
                    print(f"[DEBUG] Normalized end: '{end_normalized}'")
                    print(f"[DEBUG] Search range preview: '{search_text[:200]}...'")
                    continue

                # Reduce confidence for fuzzy end match
                match_confidence *= end_score
                print(f"[INFO] Fuzzy matched end with confidence {end_score:.2f}")

            # Check if this range overlaps with already used ranges
            if SentenceCitationService._overlaps_used_ranges(start_pos, end_pos, used_ranges):
                continue

            # Extract the matched content and map to original spans
            matched_citation = SentenceCitationService._extract_citation_from_range(
                start_pos,
                end_pos,
                full_text,
                position_map,
                confidence=match_confidence
            )

            if matched_citation:
                citations.append(matched_citation)
                used_ranges.append((start_pos, end_pos))

        return citations

    @staticmethod
    def _build_searchable_text(sentence_mapping: List[Dict[str, Any]]) -> tuple:
        """
        Build a searchable text string from sentence mapping with position tracking.

        Handles multiple formats:
        1. PDF format: {"spans": [{"content": "...", "bbox": [...]}], "page_index": 0}
        2. Simple format: {"content": "...", "bbox": [...]}
        3. Video format: {"text content": "...", "start time": 0, "speaker": "..."}

        Returns:
            (full_text, position_map)
            position_map: list of (char_start, char_end, block_idx, span_idx, span_data)
        """
        full_text = ""
        position_map = []

        for block_idx, block in enumerate(sentence_mapping):
            # Handle different formats
            content = ""
            page_index = 0
            block_type = "text"
            bbox = []

            if "spans" in block:
                # PDF format with spans
                spans = block.get("spans", [])
                page_index = block.get("page_index", 0)
                block_type = block.get("block_type", "text")

                for span_idx, span in enumerate(spans):
                    content = span.get("content", "")
                    if not content:
                        continue

                    char_start = len(full_text)
                    full_text += content
                    char_end = len(full_text)

                    position_map.append({
                        "char_start": char_start,
                        "char_end": char_end,
                        "block_idx": block_idx,
                        "span_idx": span_idx,
                        "content": content,
                        "bbox": span.get("bbox", []),
                        "page_index": page_index,
                        "block_type": block_type
                    })

                    # Add space between spans for natural text flow
                    full_text += " "

            elif "text content" in block:
                # Video transcript format
                content = block.get("text content", "")
                if not content:
                    continue

                char_start = len(full_text)
                full_text += content
                char_end = len(full_text)

                # For video transcripts, use timestamp as "page" indicator
                start_time = block.get("start time", 0)

                position_map.append({
                    "char_start": char_start,
                    "char_end": char_end,
                    "block_idx": block_idx,
                    "span_idx": 0,
                    "content": content,
                    "bbox": [],  # Videos don't have bboxes
                    "page_index": int(start_time),  # Use timestamp as page
                    "block_type": block.get("speaker", "text")
                })

                full_text += " "

            elif "content" in block:
                # Simple format
                content = block.get("content", "")
                if not content:
                    continue

                char_start = len(full_text)
                full_text += content
                char_end = len(full_text)

                position_map.append({
                    "char_start": char_start,
                    "char_end": char_end,
                    "block_idx": block_idx,
                    "span_idx": 0,
                    "content": content,
                    "bbox": block.get("bbox", []),
                    "page_index": block.get("page_index", 0),
                    "block_type": block.get("block_type", "text")
                })

                full_text += " "

        return full_text, position_map

    @staticmethod
    def _fuzzy_find_start(start_normalized: str, full_text: str, threshold: float = 0.85) -> tuple:
        """
        Find start text in full_text using fuzzy matching with sliding window.

        Args:
            start_normalized: Normalized start text to find
            full_text: Full normalized text to search in
            threshold: Minimum similarity score (0.0-1.0)

        Returns:
            Tuple of (position, confidence_score) or (-1, 0.0) if not found
        """
        start_len = len(start_normalized)
        best_pos = -1
        best_score = 0.0

        # Slide window through full text
        for i in range(len(full_text) - start_len + 1):
            window = full_text[i:i+start_len]
            similarity = SequenceMatcher(None, start_normalized, window).ratio()

            if similarity > best_score and similarity >= threshold:
                best_score = similarity
                best_pos = i

        return (best_pos, best_score) if best_pos != -1 else (-1, 0.0)

    @staticmethod
    def _fuzzy_find_end(end_normalized: str, search_text: str, offset: int, threshold: float = 0.85) -> tuple:
        """
        Find end text in search_text using fuzzy matching.

        Args:
            end_normalized: Normalized end text to find
            search_text: Text to search within
            offset: Offset to add to position (for absolute positioning)
            threshold: Minimum similarity score (0.0-1.0)

        Returns:
            Tuple of (absolute_position, confidence_score) or (-1, 0.0) if not found
        """
        end_len = len(end_normalized)
        best_pos = -1
        best_score = 0.0

        # Slide window through search text
        for i in range(len(search_text) - end_len + 1):
            window = search_text[i:i+end_len]
            similarity = SequenceMatcher(None, end_normalized, window).ratio()

            if similarity > best_score and similarity >= threshold:
                best_score = similarity
                best_pos = offset + i + end_len

        return (best_pos, best_score) if best_pos != -1 else (-1, 0.0)

    @staticmethod
    def _overlaps_used_ranges(start: int, end: int, used_ranges: List[tuple]) -> bool:
        """Check if range overlaps with any already used ranges."""
        for used_start, used_end in used_ranges:
            if not (end <= used_start or start >= used_end):
                return True
        return False

    @staticmethod
    def _match_to_sentences_direct(
        mentioned_contexts: List[Dict[str, str]],
        sentence_mapping: List[Dict[str, Any]]
    ) -> List[SentenceCitation]:
        """
        Direct sentence matching for 1-to-1 sentence-bbox mappings.

        This finds ALL sentences within a cited range (from start to end words),
        returning multiple citations when a context spans multiple sentences.

        Supports two formats:
        1. Simple format: {"content": "...", "bbox": [x1, y1, x2, y2]}
        2. Complex format: {"page_index": 0, "block_type": "text", "spans": [...]}

        Args:
            mentioned_contexts: List of dicts with 'start' and 'end' word markers
            sentence_mapping: List of sentence blocks from extra_info

        Returns:
            List of SentenceCitation objects (multiple citations per context if it spans multiple sentences)
        """
        citations = []
        used_sentences = set()  # Track by bbox_tuple to avoid duplicates

        for context in mentioned_contexts:
            start_text = context.get("start", "")
            end_text = context.get("end", "")

            if not start_text or not end_text:
                print(f"[WARNING] Missing start or end in context: {context}")
                continue

            # Normalize for matching
            start_normalized = SentenceCitationService._normalize_text(start_text)
            end_normalized = SentenceCitationService._normalize_text(end_text)

            # Find start and end sentence indices
            start_idx = None
            end_idx = None
            start_confidence = 0.0
            end_confidence = 0.0

            # Parse all sentences first
            parsed_sentences = []
            for idx, sentence_obj in enumerate(sentence_mapping):
                # Handle both simple and complex formats
                if "content" in sentence_obj and "bbox" in sentence_obj:
                    sentence_content = sentence_obj.get("content", "")
                    bbox = sentence_obj.get("bbox", [])
                    page_index = sentence_obj.get("page_index", 0)
                    block_type = sentence_obj.get("block_type", "text")
                    all_bboxes = [bbox] if bbox else []
                elif "spans" in sentence_obj:
                    sentence_content = ""
                    for span in sentence_obj.get("spans", []):
                        sentence_content += span.get("content", "")
                    page_index = sentence_obj.get("page_index", 0)
                    block_type = sentence_obj.get("block_type", "text")
                    spans = sentence_obj.get("spans", [])
                    if not spans or not spans[0].get("bbox"):
                        continue
                    bbox = spans[0].get("bbox", [])
                    all_bboxes = [span.get("bbox", []) for span in spans if span.get("bbox")]
                else:
                    continue

                if not sentence_content or not bbox:
                    continue

                parsed_sentences.append({
                    "idx": idx,
                    "content": sentence_content,
                    "normalized": SentenceCitationService._normalize_text(sentence_content),
                    "bbox": bbox,
                    "page_index": page_index,
                    "block_type": block_type,
                    "all_bboxes": all_bboxes
                })

            # Find the start sentence (sentence that contains or matches start_text)
            for i, sent in enumerate(parsed_sentences):
                if sent["normalized"].startswith(start_normalized) or start_normalized in sent["normalized"]:
                    # Exact match or contains
                    start_idx = i
                    start_confidence = 1.0
                    break
                else:
                    # Fuzzy match for start
                    similarity = SequenceMatcher(None,
                        sent["normalized"][:len(start_normalized)] if len(sent["normalized"]) >= len(start_normalized) else sent["normalized"],
                        start_normalized
                    ).ratio()
                    if similarity >= 0.85 and similarity > start_confidence:
                        start_idx = i
                        start_confidence = similarity

            if start_idx is None:
                print(f"[WARNING] Could not find start sentence for: '{start_text[:50]}'")
                continue

            # Find the end sentence (sentence that contains or matches end_text)
            # Search from start_idx onwards
            for i in range(start_idx, len(parsed_sentences)):
                sent = parsed_sentences[i]
                if sent["normalized"].endswith(end_normalized) or end_normalized in sent["normalized"]:
                    # Exact match or contains
                    end_idx = i
                    end_confidence = 1.0
                    break
                else:
                    # Fuzzy match for end
                    similarity = SequenceMatcher(None,
                        sent["normalized"][-len(end_normalized):] if len(sent["normalized"]) >= len(end_normalized) else sent["normalized"],
                        end_normalized
                    ).ratio()
                    if similarity >= 0.85 and similarity > end_confidence:
                        end_idx = i
                        end_confidence = similarity

            if end_idx is None:
                print(f"[WARNING] Could not find end sentence for: '{end_text[:50]}'")
                # If we can't find end, just use the start sentence
                end_idx = start_idx
                end_confidence = start_confidence

            # Extract all sentences from start_idx to end_idx (inclusive)
            overall_confidence = (start_confidence + end_confidence) / 2.0

            for i in range(start_idx, end_idx + 1):
                sent = parsed_sentences[i]
                bbox_key = tuple(sent["bbox"])

                # Skip if already used
                if bbox_key in used_sentences:
                    continue

                citation = SentenceCitation(
                    content=sent["content"].strip(),
                    page_index=sent["page_index"],
                    bbox=sent["bbox"],
                    block_type=sent["block_type"],
                    bboxes=sent["all_bboxes"] if len(sent["all_bboxes"]) > 1 else None,
                    confidence=overall_confidence
                )

                citations.append(citation)
                used_sentences.add(bbox_key)

        return citations

    @staticmethod
    def _extract_citation_from_range(
        start_pos: int,
        end_pos: int,
        full_text: str,
        position_map: List[Dict[str, Any]],
        confidence: float = 1.0
    ) -> Optional[SentenceCitation]:
        """
        Extract citation information from character range.

        Collects all bboxes that overlap with the citation range for proper multi-line highlighting.
        """
        overlapping_spans = []

        # Collect all spans that overlap with the citation range
        for pos_info in position_map:
            char_start = pos_info["char_start"]
            char_end = pos_info["char_end"]

            # Check if this span overlaps with our range
            if not (end_pos <= char_start or start_pos >= char_end):
                bbox = pos_info["bbox"]
                if len(bbox) == 4:
                    overlapping_spans.append(pos_info)

        if not overlapping_spans:
            return None

        # Extract the actual matched content from full_text
        matched_content = full_text[start_pos:end_pos].strip()

        # Use first span for primary fields
        first_span = overlapping_spans[0]

        # Merge overlapping bboxes on the same page
        merged_bboxes = SentenceCitationService._merge_overlapping_bboxes(overlapping_spans)

        return SentenceCitation(
            content=matched_content,
            page_index=first_span["page_index"],
            bbox=merged_bboxes[0],  # Primary bbox (first region)
            block_type=first_span["block_type"],
            bboxes=merged_bboxes if len(merged_bboxes) > 1 else None,  # List of distinct bboxes
            confidence=confidence
        )

    @staticmethod
    def _merge_overlapping_bboxes(spans: List[Dict[str, Any]]) -> List[List[float]]:
        """
        Merge overlapping or identical bboxes on the same page.

        Args:
            spans: List of span dicts with bbox, page_index

        Returns:
            List of merged/distinct bboxes
        """
        if not spans:
            return []

        # Group spans by page
        page_groups = {}
        for span in spans:
            page_idx = span.get("page_index", 0)
            if page_idx not in page_groups:
                page_groups[page_idx] = []
            page_groups[page_idx].append(span["bbox"])

        result_bboxes = []

        # Process each page separately
        for page_idx, bboxes in sorted(page_groups.items()):
            merged = SentenceCitationService._merge_bboxes_on_page(bboxes)
            result_bboxes.extend(merged)

        return result_bboxes

    @staticmethod
    def _merge_bboxes_on_page(bboxes: List[List[float]]) -> List[List[float]]:
        """
        Merge overlapping bboxes on a single page.

        Two bboxes are merged if they are identical or overlap.
        """
        if not bboxes:
            return []

        # Remove exact duplicates first
        unique_bboxes = []
        seen = set()
        for bbox in bboxes:
            bbox_tuple = tuple(bbox)
            if bbox_tuple not in seen:
                unique_bboxes.append(bbox)
                seen.add(bbox_tuple)

        if len(unique_bboxes) == 1:
            return unique_bboxes

        # Check for overlaps and merge
        merged = []
        used = [False] * len(unique_bboxes)

        for i in range(len(unique_bboxes)):
            if used[i]:
                continue

            current = unique_bboxes[i]
            x1, y1, x2, y2 = current

            # Find all bboxes that overlap with current
            overlapping_indices = [i]
            for j in range(i + 1, len(unique_bboxes)):
                if used[j]:
                    continue

                ox1, oy1, ox2, oy2 = unique_bboxes[j]

                # Check if bboxes overlap
                if not (x2 < ox1 or x1 > ox2 or y2 < oy1 or y1 > oy2):
                    # They overlap, merge them
                    x1 = min(x1, ox1)
                    y1 = min(y1, oy1)
                    x2 = max(x2, ox2)
                    y2 = max(y2, oy2)
                    overlapping_indices.append(j)

            # Mark all overlapping as used
            for idx in overlapping_indices:
                used[idx] = True

            # Add merged bbox
            merged.append([x1, y1, x2, y2])

        return merged

    @staticmethod
    def _normalize_text(text: str) -> str:
        """Normalize text for comparison (remove extra whitespace, lowercase)"""
        # Normalize different types of apostrophes and quotes to standard ones
        text = text.replace(''', "'").replace(''', "'")  # Smart quotes to straight quotes
        text = text.replace('"', '"').replace('"', '"')  # Smart double quotes
        text = text.replace('–', '-').replace('—', '-')  # En/em dashes to hyphen

        # Remove extra whitespace
        text = re.sub(r'\s+', ' ', text)
        # Strip and lowercase
        text = text.strip().lower()
        # Remove common punctuation at the end
        text = text.rstrip('.,!?;:')
        return text

    @staticmethod
    def parse_structured_response(response_text: str) -> Dict[str, Any]:
        try:
            # Try to extract JSON from response (might be in code blocks)
            json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', response_text, re.DOTALL)
            if json_match:
                json_str = json_match.group(1)
            else:
                # Try to find raw JSON object
                json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
                if json_match:
                    json_str = json_match.group(0)
                else:
                    print("[WARNING] No JSON object found in response")
                    return {
                        "answer": response_text,
                        "mentioned_contexts": []
                    }

            parsed = json.loads(json_str)

            # Validate against JSON schema if jsonschema is available
            if JSONSCHEMA_AVAILABLE:
                try:
                    jsonschema.validate(instance=parsed, schema=CITATION_JSON_SCHEMA)
                    print("[INFO] JSON response validated successfully against schema")
                except jsonschema.ValidationError as ve:
                    print(f"[WARNING] JSON schema validation failed: {ve.message}")
                    print(f"[WARNING] Failed at path: {' -> '.join(str(p) for p in ve.path)}")
                    # Continue with manual validation as fallback
                except jsonschema.SchemaError as se:
                    print(f"[ERROR] Invalid JSON schema definition: {se.message}")

            # Handle both new nested format and legacy flat format
            mentioned_contexts = []

            if "references" in parsed and isinstance(parsed["references"], list):
                # New format: references is array of {reference, mentioned_contexts}
                for ref_obj in parsed["references"]:
                    if not isinstance(ref_obj, dict):
                        continue

                    ref_num = ref_obj.get("reference")
                    ref_contexts = ref_obj.get("mentioned_contexts", [])

                    # Flatten: add reference number to each mentioned_context
                    for ctx in ref_contexts:
                        if isinstance(ctx, dict) and "start" in ctx and "end" in ctx:
                            mentioned_contexts.append({
                                "reference": ref_num,
                                "start": ctx["start"],
                                "end": ctx["end"]
                            })
                        else:
                            print(f"[WARNING] Invalid mentioned_context format: {ctx}")

            elif "mentioned_contexts" in parsed:
                # Legacy format: flat mentioned_contexts array
                legacy_contexts = parsed.get("mentioned_contexts", [])
                for ctx in legacy_contexts:
                    if isinstance(ctx, dict) and "reference" in ctx and "start" in ctx and "end" in ctx:
                        mentioned_contexts.append(ctx)
                    elif isinstance(ctx, dict) and "start" in ctx and "end" in ctx:
                        # Missing reference number - try to continue but warn
                        print(f"[WARNING] Context missing 'reference' field: {ctx}")
                        mentioned_contexts.append(ctx)
                    elif isinstance(ctx, str):
                        # Very old format: string - skip with warning
                        print(f"[WARNING] Old string format detected, skipping: {ctx[:50]}...")

            return {
                "answer": parsed.get("answer", response_text),
                "mentioned_contexts": mentioned_contexts
            }

        except (json.JSONDecodeError, ValueError) as e:
            print(f"[WARNING] Failed to parse structured response: {e}")
            # Fallback: treat entire response as answer
            return {
                "answer": response_text,
                "mentioned_contexts": []
            }

    @staticmethod
    def build_citation_prompt_addition() -> str:
        """
        Build the additional system prompt text for citation tracking.

        This should be added to the system message to instruct the model
        to return structured output with references (with nested contexts) → answer format.
        """
        return """
IMPORTANT: When answering, you must return your response in the following JSON format:
{
    "references": [
        {
            "reference": 1,
            "mentioned_contexts": [
                {
                    "start": "first few words of passage",
                    "end": "last few words of passage"
                }
            ]
        },
        {
            "reference": 2,
            "mentioned_contexts": [
                {
                    "start": "first few words",
                    "end": "last few words"
                }
            ]
        }
    ],
    "answer": "Your complete answer here based on the references you identified..."
}

STEP-BY-STEP PROCESS:
1. REFERENCES: Declare which references you'll use and specify the parts:
   - For each relevant reference:
     * "reference": the reference number (from "Reference Number: N")
     * "mentioned_contexts": array of specific passages you'll cite
   - For each passage:
     * "start": first 3-5 words from the passage (approximate is fine)
     * "end": last 3-5 words from the passage (approximate is fine)

2. ANSWER: Generate your complete answer using the references you declared.

EXAMPLE:
{
    "references": [
        {
            "reference": 1,
            "mentioned_contexts": [
                {
                    "start": "Variables are names bound",
                    "end": "to values in Python"
                }
            ]
        }
    ],
    "answer": "Variables in Python are names bound to values. They act as labels that reference objects in memory."
}
"""
