#!/usr/bin/env python3
"""
Script to merge incomplete sentences in preproc_blocks while preserving content type separation.

Rules:
1. Don't merge different content types (e.g., title and text)
2. A new sentence starts with sentence-ending punctuation (. ! ?) followed by a capital letter
3. Merge spans/lines that contain incomplete sentences into complete ones
"""

import json
import re
from typing import List, Dict, Any
from copy import deepcopy


def is_sentence_end(text: str) -> bool:
    """Check if text ends with sentence-ending punctuation."""
    text = text.strip()
    return bool(re.search(r'[.!?]\s*$', text))


def starts_with_capital(text: str) -> bool:
    """Check if text starts with a capital letter."""
    text = text.strip()
    return len(text) > 0 and text[0].isupper()


def is_new_sentence_start(prev_text: str, current_text: str) -> bool:
    """
    Determine if current text starts a new sentence.
    A new sentence should:
    - Previous text ends with . ! ?
    - Current text starts with a capital letter

    If either condition is not met, we should continue merging (incomplete sentence).
    """
    if not prev_text:
        return True

    # Only start a new sentence if BOTH conditions are met
    # Otherwise, keep merging (incomplete sentence)
    return is_sentence_end(prev_text) and starts_with_capital(current_text)


def get_text_from_span(span: Dict[str, Any]) -> str:
    """Extract text content from a span."""
    return span.get('content', '').strip()


def remove_score_from_span(span: Dict[str, Any]) -> Dict[str, Any]:
    """Remove score field from span."""
    if 'score' in span:
        del span['score']
    return span


def split_span_at_sentence_boundaries(span: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Split a span if it contains sentence boundaries.
    Returns list of spans (may be just one if no boundaries found).
    """
    content = span.get('content', '').strip()
    if not content:
        return [span]

    # Find sentence boundaries within the content
    pattern = r'([.!?])\s+(?=[A-Z])'
    matches = list(re.finditer(pattern, content))

    if not matches:
        # No boundaries, return as-is
        return [span]

    # Split at boundaries
    boundaries = [0] + [m.end() for m in matches] + [len(content)]
    new_spans = []
    bbox = span.get('bbox', [0, 0, 0, 0])
    bbox_width = bbox[2] - bbox[0]

    for i in range(len(boundaries) - 1):
        start = boundaries[i]
        end = boundaries[i + 1]
        text = content[start:end].strip()

        if not text:
            continue

        # Estimate bbox for this sub-span
        char_ratio_start = start / len(content) if len(content) > 0 else 0
        char_ratio_end = end / len(content) if len(content) > 0 else 1

        new_span = deepcopy(span)
        new_span['content'] = text
        new_span['bbox'] = [
            int(bbox[0] + bbox_width * char_ratio_start),
            bbox[1],
            int(bbox[0] + bbox_width * char_ratio_end),
            bbox[3]
        ]
        # Remove score field
        remove_score_from_span(new_span)
        new_spans.append(new_span)

    return new_spans


def merge_spans_in_line(spans: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Merge spans within a line that form incomplete sentences."""
    if not spans:
        return spans

    # First, split any spans that contain sentence boundaries
    split_spans = []
    for span in spans:
        split_spans.extend(split_span_at_sentence_boundaries(span))

    # Now merge spans that form incomplete sentences
    merged_spans = []
    current_span = deepcopy(split_spans[0])
    # Remove score from first span
    remove_score_from_span(current_span)

    for i in range(1, len(split_spans)):
        next_span = split_spans[i]
        current_text = get_text_from_span(current_span)
        next_text = get_text_from_span(next_span)

        # Check if we should start a new span
        if is_new_sentence_start(current_text, next_text):
            merged_spans.append(current_span)
            current_span = deepcopy(next_span)
            # Remove score from new span
            remove_score_from_span(current_span)
        else:
            # Merge the spans
            current_span['content'] = current_text + ' ' + next_text
            # Expand bbox to include both spans
            current_span['bbox'] = [
                min(current_span['bbox'][0], next_span['bbox'][0]),
                min(current_span['bbox'][1], next_span['bbox'][1]),
                max(current_span['bbox'][2], next_span['bbox'][2]),
                max(current_span['bbox'][3], next_span['bbox'][3])
            ]

    merged_spans.append(current_span)
    return merged_spans


def merge_lines_in_block(lines: List[Dict[str, Any]], block_type: str) -> List[Dict[str, Any]]:
    """Merge lines within a block that form incomplete sentences."""
    if not lines or block_type == 'title':
        # Don't merge title blocks
        return lines

    merged_lines = []
    current_line = None

    for line in lines:
        # First merge spans within this line
        line['spans'] = merge_spans_in_line(line.get('spans', []))

        if current_line is None:
            current_line = deepcopy(line)
            continue

        # Get the last text from current line and first text from next line
        current_text = ''
        if current_line.get('spans'):
            current_text = get_text_from_span(current_line['spans'][-1])

        next_text = ''
        if line.get('spans'):
            next_text = get_text_from_span(line['spans'][0])

        # Check if we should start a new line
        if is_new_sentence_start(current_text, next_text):
            merged_lines.append(current_line)
            current_line = deepcopy(line)
        else:
            # Merge the lines
            current_line['spans'].extend(line['spans'])
            # Merge spans after extending to ensure continuous text is in one span
            current_line['spans'] = merge_spans_in_line(current_line['spans'])
            # Expand bbox to include both lines
            current_line['bbox'] = [
                min(current_line['bbox'][0], line['bbox'][0]),
                min(current_line['bbox'][1], line['bbox'][1]),
                max(current_line['bbox'][2], line['bbox'][2]),
                max(current_line['bbox'][3], line['bbox'][3])
            ]

    if current_line:
        merged_lines.append(current_line)

    return merged_lines


def merge_blocks(blocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Merge blocks that contain incomplete sentences.
    Rules:
    - Don't merge different block types (title, text, etc.)
    - Merge only if previous block doesn't end with complete sentence
    """
    if not blocks:
        return blocks

    # First, merge lines within each block
    for block in blocks:
        block_type = block.get('type', 'text')
        block['lines'] = merge_lines_in_block(block.get('lines', []), block_type)

    # Now merge blocks if needed
    merged_blocks = []
    current_block = None

    for block in blocks:
        if current_block is None:
            current_block = deepcopy(block)
            continue

        # Check if blocks can be merged
        current_type = current_block.get('type')
        next_type = block.get('type')

        # Allow merging inline_equation with text blocks
        can_merge_types = (
            current_type == next_type or
            (current_type in ['text', 'inline_equation'] and next_type in ['text', 'inline_equation'])
        )

        if not can_merge_types:
            merged_blocks.append(current_block)
            current_block = deepcopy(block)
            continue

        # Don't merge title blocks
        if current_block.get('type') == 'title':
            merged_blocks.append(current_block)
            current_block = deepcopy(block)
            continue

        # Check vertical distance between blocks
        # If blocks are too far apart (gap > 10px), don't merge
        current_bbox = current_block.get('bbox', [0, 0, 0, 0])
        next_bbox = block.get('bbox', [0, 0, 0, 0])
        vertical_gap = next_bbox[1] - current_bbox[3]  # gap = next_top - current_bottom

        if vertical_gap > 10:
            # Blocks are visually separated, don't merge
            merged_blocks.append(current_block)
            current_block = deepcopy(block)
            continue

        # Get last text from current block and first text from next block
        current_text = ''
        if current_block.get('lines') and current_block['lines'][-1].get('spans'):
            current_text = get_text_from_span(current_block['lines'][-1]['spans'][-1])

        next_text = ''
        if block.get('lines') and block['lines'][0].get('spans'):
            next_text = get_text_from_span(block['lines'][0]['spans'][0])

        # Check if we should start a new block
        if is_new_sentence_start(current_text, next_text):
            merged_blocks.append(current_block)
            current_block = deepcopy(block)
        else:
            # Merge the blocks
            current_block['lines'].extend(block['lines'])
            # Re-merge lines after extending to handle cross-block sentence continuations
            current_block['lines'] = merge_lines_in_block(current_block['lines'], current_block.get('type', 'text'))

            # When merging inline_equation with text, keep type as 'text'
            if current_type in ['text', 'inline_equation'] and next_type in ['text', 'inline_equation']:
                current_block['type'] = 'text'

            # Keep the smaller index when merging
            current_index = current_block.get('index', float('inf'))
            next_index = block.get('index', float('inf'))
            current_block['index'] = min(current_index, next_index)

            # Expand bbox to include both blocks
            current_block['bbox'] = [
                min(current_block['bbox'][0], block['bbox'][0]),
                min(current_block['bbox'][1], block['bbox'][1]),
                max(current_block['bbox'][2], block['bbox'][2]),
                max(current_block['bbox'][3], block['bbox'][3])
            ]

    if current_block:
        merged_blocks.append(current_block)

    return merged_blocks


def process_pdf_json(input_path: str, output_path: str):
    """Process the PDF JSON file and merge incomplete sentences."""
    print(f"Reading {input_path}...")
    with open(input_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # Process each page
    total_blocks_before = 0
    total_blocks_after = 0

    for page_idx, page in enumerate(data['pdf_info']):
        blocks_before = len(page['preproc_blocks'])
        total_blocks_before += blocks_before

        # Merge blocks
        page['preproc_blocks'] = merge_blocks(page['preproc_blocks'])

        blocks_after = len(page['preproc_blocks'])
        total_blocks_after += blocks_after

        # Remove para_blocks and discarded_blocks to keep only preproc_blocks
        if 'para_blocks' in page:
            del page['para_blocks']
        if 'discarded_blocks' in page:
            del page['discarded_blocks']

        # Final cleanup: remove all score fields from all spans and reassign indexes
        for block_idx, block in enumerate(page['preproc_blocks']):
            # Reassign block index sequentially
            block['index'] = block_idx

            # Reassign line indexes sequentially within each block
            for line_idx, line in enumerate(block['lines']):
                line['index'] = line_idx

                for span in line['spans']:
                    if 'score' in span:
                        del span['score']

        print(f"Page {page_idx + 1}: {blocks_before} blocks -> {blocks_after} blocks ({blocks_before - blocks_after} merged)")

    print(f"\nTotal: {total_blocks_before} blocks -> {total_blocks_after} blocks")
    print(f"Merged {total_blocks_before - total_blocks_after} blocks")

    # Save the result
    print(f"\nSaving to {output_path}...")
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print("Done!")


if __name__ == '__main__':
    import sys

    if len(sys.argv) < 2:
        input_file = '/home/bot/bot/yk/YK_final/test_folder_output/disc01/disc01.pdf_middle.json'
        output_file = '/home/bot/bot/yk/YK_final/test_folder_output/disc01/disc01.pdf_middle_merged.json'
    else:
        input_file = sys.argv[1]
        output_file = sys.argv[2] if len(sys.argv) > 2 else input_file.replace('.json', '_merged.json')

    process_pdf_json(input_file, output_file)
