#!/usr/bin/env python3
"""
Script to split and merge blocks based on complete sentences.

Strategy:
1. Extract all text from blocks while preserving order
2. Identify sentence boundaries using punctuation + capital letter
3. Create new blocks for each complete sentence or sentence group
4. Preserve bbox information based on the original spans
"""

import json
import re
from typing import List, Dict, Any, Tuple
from copy import deepcopy


def find_sentence_boundaries(text: str) -> List[int]:
    """
    Find positions where sentences end and new ones begin.
    Returns list of positions (after the space following punctuation).
    """
    # Pattern: sentence-ending punctuation followed by space(s) and capital letter
    pattern = r'([.!?])\s+(?=[A-Z])'

    boundaries = [0]  # Start of text
    for match in re.finditer(pattern, text):
        # Position after the punctuation and space
        boundaries.append(match.end())

    boundaries.append(len(text))  # End of text
    return boundaries


def extract_sentences(text: str) -> List[str]:
    """Split text into sentences."""
    boundaries = find_sentence_boundaries(text)
    sentences = []

    for i in range(len(boundaries) - 1):
        start = boundaries[i]
        end = boundaries[i + 1]
        sentence = text[start:end].strip()
        if sentence:
            sentences.append(sentence)

    return sentences


def get_all_text_from_block(block: Dict[str, Any]) -> str:
    """Extract all text content from a block in order."""
    texts = []
    for line in block.get('lines', []):
        for span in line.get('spans', []):
            content = span.get('content', '').strip()
            if content:
                texts.append(content)
    return ' '.join(texts)


def split_block_by_sentences(block: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Split a single block into multiple blocks based on sentence boundaries.
    Each new block will contain complete sentences.
    """
    block_type = block.get('type', 'text')

    # Don't split title blocks
    if block_type == 'title':
        return [block]

    # Get all text from the block
    full_text = get_all_text_from_block(block)

    # Find sentences
    sentences = extract_sentences(full_text)

    # If only one sentence or no splitting needed, return original block
    if len(sentences) <= 1:
        return [block]

    # Create new blocks for each sentence
    # For now, we'll create simplified blocks with combined text
    # In a more sophisticated version, we'd track exact span boundaries
    new_blocks = []
    bbox = block.get('bbox', [0, 0, 0, 0])

    # Estimate bbox height per sentence
    total_height = bbox[3] - bbox[1]
    height_per_sentence = total_height / len(sentences)

    for i, sentence in enumerate(sentences):
        # Create new block
        new_block = {
            'type': block_type,
            'bbox': [
                bbox[0],
                int(bbox[1] + i * height_per_sentence),
                bbox[2],
                int(bbox[1] + (i + 1) * height_per_sentence)
            ],
            'lines': [
                {
                    'bbox': [
                        bbox[0],
                        int(bbox[1] + i * height_per_sentence),
                        bbox[2],
                        int(bbox[1] + (i + 1) * height_per_sentence)
                    ],
                    'spans': [
                        {
                            'bbox': [
                                bbox[0],
                                int(bbox[1] + i * height_per_sentence),
                                bbox[2],
                                int(bbox[1] + (i + 1) * height_per_sentence)
                            ],
                            'content': sentence,
                            'type': 'text',
                            'score': 1.0
                        }
                    ],
                    'index': i
                }
            ],
            'index': block.get('index', 0) + i
        }
        new_blocks.append(new_block)

    return new_blocks


def process_blocks_with_sentence_splitting(blocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Process all blocks:
    1. Split blocks that contain multiple sentences
    2. Respect visual spacing (don't merge blocks with large gaps)
    """
    if not blocks:
        return blocks

    processed_blocks = []

    for block in blocks:
        # Split block by sentences
        split_blocks = split_block_by_sentences(block)
        processed_blocks.extend(split_blocks)

    return processed_blocks


def process_pdf_json(input_path: str, output_path: str):
    """Process the PDF JSON file and split/merge based on sentences."""
    print(f"Reading {input_path}...")
    with open(input_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # Process each page
    total_blocks_before = 0
    total_blocks_after = 0

    for page_idx, page in enumerate(data['pdf_info']):
        blocks_before = len(page['preproc_blocks'])
        total_blocks_before += blocks_before

        # Process blocks with sentence splitting
        page['preproc_blocks'] = process_blocks_with_sentence_splitting(page['preproc_blocks'])

        blocks_after = len(page['preproc_blocks'])
        total_blocks_after += blocks_after

        change = blocks_after - blocks_before
        if change > 0:
            print(f"Page {page_idx + 1}: {blocks_before} blocks -> {blocks_after} blocks (+{change} split)")
        elif change < 0:
            print(f"Page {page_idx + 1}: {blocks_before} blocks -> {blocks_after} blocks ({abs(change)} merged)")
        else:
            print(f"Page {page_idx + 1}: {blocks_before} blocks (no change)")

    print(f"\nTotal: {total_blocks_before} blocks -> {total_blocks_after} blocks")

    if total_blocks_after > total_blocks_before:
        print(f"Split {total_blocks_after - total_blocks_before} blocks")
    elif total_blocks_after < total_blocks_before:
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
        output_file = '/home/bot/bot/yk/YK_final/test_folder_output/disc01/disc01.pdf_middle_split.json'
    else:
        input_file = sys.argv[1]
        output_file = sys.argv[2] if len(sys.argv) > 2 else input_file.replace('.json', '_split.json')

    process_pdf_json(input_file, output_file)
