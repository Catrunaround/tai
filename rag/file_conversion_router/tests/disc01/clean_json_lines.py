#!/usr/bin/env python3
"""
Script to clean PDF middle JSON and extract line information.
Merges spans across lines to form complete sentences.

Usage:
    python clean_json_lines.py [input_json] [output_json]
"""

import json
import re
from typing import List, Dict, Any, Tuple


def find_sentence_boundaries(text: str) -> List[int]:
    """
    Find positions where sentences end in text.
    Returns list of positions right after sentence-ending punctuation.
    """
    # Pattern: sentence-ending punctuation (. ! ?) followed by space and capital letter, or end of string
    pattern = r'([.!?])\s+(?=[A-Z])|([.!?])\s*$'

    boundaries = []
    for match in re.finditer(pattern, text):
        # Position right after the punctuation and space
        boundaries.append(match.end())

    return boundaries


def ends_with_complete_sentence(text: str) -> bool:
    """Check if text ends with complete sentence (ends with . ! ?)."""
    text = text.strip()
    return len(text) > 0 and text[-1] in '.!?'


def merge_bboxes(bboxes: List[List[int]]) -> List[int]:
    """Merge multiple bboxes into one encompassing bbox."""
    if not bboxes:
        return [0, 0, 0, 0]

    x1 = min(bbox[0] for bbox in bboxes)
    y1 = min(bbox[1] for bbox in bboxes)
    x2 = max(bbox[2] for bbox in bboxes)
    y2 = max(bbox[3] for bbox in bboxes)

    return [x1, y1, x2, y2]


def calculate_font_size(bbox: List[int]) -> int:
    """Estimate font size from bbox height."""
    return bbox[3] - bbox[1]


def calculate_vertical_gap(bbox1: List[int], bbox2: List[int]) -> int:
    """
    Calculate vertical gap between two bboxes.
    Returns the distance between bottom of bbox1 and top of bbox2.
    """
    return bbox2[1] - bbox1[3]


def should_merge_with_next(
    current_text: str,
    first_line_bboxes: List[List[int]],
    all_bboxes: List[List[int]],
    next_bboxes: List[List[int]],
    block_type: str,
    lines_merged: int
) -> bool:
    """
    Decide if we should merge current text with next line.

    Args:
        current_text: Current accumulated text
        first_line_bboxes: Bboxes from first line only (for font size calculation)
        all_bboxes: All accumulated bboxes from merged lines (for gap calculation)
        next_bboxes: List of bboxes for next line
        block_type: Type of block (title, text, etc.)
        lines_merged: Number of lines already merged

    Returns:
        True if should merge with next line, False otherwise
    """
    # Don't merge titles - they're standalone
    if block_type == "title":
        return False

    # Safety limit: don't merge too many lines
    if lines_merged >= 10:
        return False

    # If sentence ends properly, don't merge
    if ends_with_complete_sentence(current_text):
        return False

    # Calculate current bbox (merged from all current bboxes)
    if not first_line_bboxes or not all_bboxes or not next_bboxes:
        return True

    # Use the SMALLEST bbox height from FIRST LINE for font size (most accurate for single line)
    # This avoids using accidentally merged bboxes
    font_size = min(calculate_font_size(bbox) for bbox in first_line_bboxes)

    # For gap calculation, use ALL accumulated bboxes to get the actual bottom position
    current_bbox = merge_bboxes(all_bboxes)
    next_bbox = merge_bboxes(next_bboxes)
    vertical_gap = calculate_vertical_gap(current_bbox, next_bbox)

    # Don't merge if gap is too large (more than 2x font size)
    # This prevents merging text that's visually separated
    if vertical_gap > 2 * font_size:
        return False

    # Otherwise, merge to try to complete the sentence
    return True


def combine_line_content(line: Dict[str, Any]) -> Tuple[str, List[List[int]]]:
    """
    Extract combined text and all bboxes from a line's spans.
    Returns (combined_text, list_of_bboxes)
    """
    texts = []
    bboxes = []

    for span in line.get('spans', []):
        content = span.get('content', '').strip()
        if content:
            texts.append(content)
            if 'bbox' in span:
                bboxes.append(span['bbox'])

    combined_text = ' '.join(texts)
    return combined_text, bboxes


def merge_lines_into_sentences(lines: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Merge lines so that each resulting line contains complete sentences.
    Looks ahead to combine incomplete sentences across lines.
    Uses distance checking to avoid merging visually separated text.
    """
    if not lines:
        return lines

    result = []
    i = 0

    while i < len(lines):
        current_line = lines[i]
        page_index = current_line['page_index']
        block_type = current_line['block_type']

        # Combine all spans in current line
        text, bboxes = combine_line_content(current_line)

        # If text is empty, skip
        if not text:
            i += 1
            continue

        # Store original first line bbox for font size calculation
        first_line_bboxes = bboxes[:]

        # Look ahead to complete incomplete sentences
        j = i + 1
        lines_merged = 1

        while j < len(lines):
            next_line = lines[j]

            # Only merge within same page and block type
            if (next_line['page_index'] != page_index or
                next_line['block_type'] != block_type):
                break

            # Get next line content
            next_text, next_bboxes = combine_line_content(next_line)
            if not next_text:
                j += 1
                continue

            # Check if we should merge with next line
            # Pass first line's bboxes for font size, all bboxes for gap calculation
            if not should_merge_with_next(text, first_line_bboxes, bboxes, next_bboxes, block_type, lines_merged):
                break

            # Merge with next line
            text = text + ' ' + next_text
            bboxes.extend(next_bboxes)
            lines_merged += 1
            j += 1

        # Now split text at sentence boundaries
        sentence_spans = split_into_sentence_spans(text, bboxes)

        # Create new line entries for each sentence span
        for span_content, span_bbox in sentence_spans:
            result.append({
                'index': len(result),  # Add index for each span
                'page_index': page_index,
                'block_type': block_type,
                'spans': [{
                    'bbox': span_bbox,
                    'content': span_content,
                    'type': 'text'
                }]
            })

        # Move to next unprocessed line
        i = j

    return result


def split_into_sentence_spans(text: str, bboxes: List[List[int]]) -> List[Tuple[str, List[int]]]:
    """
    Split text into sentences and assign merged bbox to each.
    Returns list of (sentence_text, merged_bbox) tuples.
    """
    # Find sentence boundaries
    boundaries = find_sentence_boundaries(text)

    # If no boundaries found, return text as single span
    if not boundaries:
        return [(text.strip(), merge_bboxes(bboxes))]

    # Split text at boundaries
    sentences = []
    start = 0

    for end in boundaries:
        sentence = text[start:end].strip()
        if sentence:
            sentences.append((sentence, merge_bboxes(bboxes)))
        start = end

    # Handle remaining text after last boundary
    if start < len(text):
        remaining = text[start:].strip()
        if remaining:
            sentences.append((remaining, merge_bboxes(bboxes)))

    return sentences if sentences else [(text.strip(), merge_bboxes(bboxes))]


def extract_lines_from_json(json_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Extract all line information from the PDF JSON structure.
    Removes line-level bbox and keeps span-level bbox (more accurate).

    Returns a list with each line's information preserved as-is.
    """
    extracted_lines = []

    pdf_info = json_data.get('pdf_info', [])

    for page_idx, page in enumerate(pdf_info):
        preproc_blocks = page.get('preproc_blocks', [])

        for block in preproc_blocks:
            block_type = block.get('type', 'unknown')
            block_index = block.get('index', -1)
            lines = block.get('lines', [])

            for line in lines:
                # Keep the line information, but remove line-level bbox and line index
                line_info = {
                    'page_index': page_idx,
                    'block_type': block_type,
                    **{k: v for k, v in line.items() if k not in ['bbox', 'index']}  # Remove line bbox and index
                }

                # Remove score from each span
                if 'spans' in line_info:
                    cleaned_spans = []
                    for span in line_info['spans']:
                        cleaned_span = {k: v for k, v in span.items() if k != 'score'}
                        cleaned_spans.append(cleaned_span)
                    line_info['spans'] = cleaned_spans

                extracted_lines.append(line_info)

    # Merge lines into sentence-based spans
    extracted_lines = merge_lines_into_sentences(extracted_lines)

    return extracted_lines


def process_pdf_json(input_path: str, output_path: str):
    """Process the PDF JSON file and extract sentence-based spans."""
    print(f"Reading {input_path}...")
    with open(input_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    print("Extracting and merging lines into sentences...")
    sentence_spans = extract_lines_from_json(data)

    num_pages = len(data.get('pdf_info', []))
    print(f"Created {len(sentence_spans)} sentence-based spans from {num_pages} pages")

    print(f"\nSaving to {output_path}...")
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(sentence_spans, f, ensure_ascii=False, indent=2)

    print("Done!")

    # Print sample
    print(f"\nFirst 3 sentence spans:")
    for i, span in enumerate(sentence_spans[:3]):
        content = span['spans'][0].get('content', '')[:80]
        print(f"  [{i}] Page {span['page_index']} ({span['block_type']}): {content}...")


if __name__ == '__main__':
    import sys

    if len(sys.argv) < 2:
        input_file = '/Users/yyk956614/tai/rag/file_conversion_router/tests/disc01/disc01.pdf_middle.json'
        output_file = '/Users/yyk956614/tai/rag/file_conversion_router/tests/disc01/disc01.pdf_lines.json'
    else:
        input_file = sys.argv[1]
        output_file = sys.argv[2] if len(sys.argv) > 2 else input_file.replace('.json', '_lines.json')

    process_pdf_json(input_file, output_file)
