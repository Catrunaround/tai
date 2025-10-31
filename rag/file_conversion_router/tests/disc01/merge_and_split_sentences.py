#!/usr/bin/env python3
"""
Script to properly handle sentence boundaries in preproc_blocks.

Strategy:
1. First merge incomplete lines/spans within blocks to form complete text
2. Split at sentence boundaries (. ! ? followed by capital letter)
3. Respect visual spacing (don't merge blocks with large vertical gaps)
4. Don't merge different block types (title vs text)

This creates blocks where each block contains complete sentences.
"""

import json
import re
from typing import List, Dict, Any
from copy import deepcopy


def find_sentence_boundaries(text: str) -> List[int]:
    """
    Find positions where new sentences start.
    Pattern: `. ! ?` followed by space(s) and a capital letter.
    Returns positions right before the capital letter.
    """
    pattern = r'([.!?])\s+(?=[A-Z])'

    boundaries = [0]  # Start
    for match in re.finditer(pattern, text):
        # Position right after the space (where new sentence starts)
        boundaries.append(match.end())

    if boundaries[-1] != len(text):
        boundaries.append(len(text))  # End

    return boundaries


def extract_all_text_from_block(block: Dict[str, Any]) -> str:
    """Extract all text from a block, joining with spaces."""
    texts = []
    for line in block.get('lines', []):
        for span in line.get('spans', []):
            content = span.get('content', '').strip()
            if content:
                texts.append(content)
    return ' '.join(texts)


def split_block_into_sentence_groups(block: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Split a block into multiple blocks based on sentence boundaries.
    Each new block contains one or more complete sentences.
    """
    block_type = block.get('type', 'text')

    # Don't split title blocks
    if block_type == 'title':
        return [block]

    # Get all text
    full_text = extract_all_text_from_block(block)

    # Find sentence boundaries
    boundaries = find_sentence_boundaries(full_text)

    # If only one sentence, return original
    if len(boundaries) <= 2:  # [start, end] means one sentence
        return [block]

    # Split into sentence groups
    # Create new blocks for each sentence group
    new_blocks = []
    bbox = block.get('bbox', [0, 0, 0, 0])

    # Calculate bbox height per sentence group
    num_groups = len(boundaries) - 1
    total_height = bbox[3] - bbox[1]
    height_per_group = total_height / num_groups if num_groups > 0 else total_height

    for i in range(num_groups):
        start_pos = boundaries[i]
        end_pos = boundaries[i + 1]
        sentence_text = full_text[start_pos:end_pos].strip()

        if not sentence_text:
            continue

        # Create new block with estimated bbox
        new_block = {
            'type': block_type,
            'bbox': [
                bbox[0],
                int(bbox[1] + i * height_per_group),
                bbox[2],
                int(bbox[1] + (i + 1) * height_per_group)
            ],
            'lines': [
                {
                    'bbox': [
                        bbox[0],
                        int(bbox[1] + i * height_per_group),
                        bbox[2],
                        int(bbox[1] + (i + 1) * height_per_group)
                    ],
                    'spans': [
                        {
                            'bbox': [
                                bbox[0],
                                int(bbox[1] + i * height_per_group),
                                bbox[2],
                                int(bbox[1] + (i + 1) * height_per_group)
                            ],
                            'content': sentence_text,
                            'type': 'text',
                            'score': 1.0
                        }
                    ],
                    'index': 0
                }
            ],
            'index': block.get('index', 0)
        }
        new_blocks.append(new_block)

    return new_blocks


def process_blocks(blocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Process blocks:
    1. Split each block at sentence boundaries
    2. Don't merge blocks with large vertical gaps (>10px)
    """
    if not blocks:
        return blocks

    processed_blocks = []

    for block in blocks:
        # Split block by sentences
        split_blocks = split_block_into_sentence_groups(block)

        for split_block in split_blocks:
            # Check if we should merge with previous block
            should_merge = False

            if processed_blocks:
                prev_block = processed_blocks[-1]

                # Same type?
                if prev_block.get('type') == split_block.get('type') != 'title':
                    # Check vertical gap
                    prev_bbox = prev_block.get('bbox', [0, 0, 0, 0])
                    curr_bbox = split_block.get('bbox', [0, 0, 0, 0])
                    vertical_gap = curr_bbox[1] - prev_bbox[3]

                    # If gap is small (<= 10px), this might be same logical block
                    # Don't merge in this case since we just split by sentences
                    # Only the spatial check prevents merging across visual boundaries
                    pass

            processed_blocks.append(split_block)

    return processed_blocks


def process_pdf_json(input_path: str, output_path: str):
    """Process the PDF JSON file."""
    print(f"Reading {input_path}...")
    with open(input_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    total_blocks_before = 0
    total_blocks_after = 0

    for page_idx, page in enumerate(data['pdf_info']):
        blocks_before = len(page['preproc_blocks'])
        total_blocks_before += blocks_before

        # Process blocks
        page['preproc_blocks'] = process_blocks(page['preproc_blocks'])

        blocks_after = len(page['preproc_blocks'])
        total_blocks_after += blocks_after

        change = blocks_after - blocks_before
        if change != 0:
            print(f"Page {page_idx + 1}: {blocks_before} blocks -> {blocks_after} blocks ({change:+d})")
        else:
            print(f"Page {page_idx + 1}: {blocks_before} blocks (unchanged)")

    print(f"\nTotal: {total_blocks_before} -> {total_blocks_after} blocks ({total_blocks_after - total_blocks_before:+d})")

    print(f"\nSaving to {output_path}...")
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print("Done!")


if __name__ == '__main__':
    import sys

    if len(sys.argv) < 2:
        input_file = '/home/bot/bot/yk/YK_final/test_folder_output/disc01/disc01.pdf_middle.json'
        output_file = '/home/bot/bot/yk/YK_final/test_folder_output/disc01/disc01.pdf_middle_final.json'
    else:
        input_file = sys.argv[1]
        output_file = sys.argv[2] if len(sys.argv) > 2 else input_file.replace('.json', '_final.json')

    process_pdf_json(input_file, output_file)
