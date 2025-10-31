"""Service for managing sentence-to-bbox mappings in the database."""

import json
import logging
import sqlite3
from pathlib import Path
from typing import List, Dict, Any, Optional


def generate_sentence_mapping_from_json(lines_json_path: str) -> List[Dict[str, Any]]:
    """
    Load a *_lines.json file and extract ordered sentence-to-bbox mappings.

    Args:
        lines_json_path: Path to the lines JSON file (e.g., disc01.pdf_lines.json)

    Returns:
        List of {"content": str, "bbox": [x1, y1, x2, y2]} dicts in order

    Example:
        >>> mapping = generate_sentence_mapping_from_json("disc01.pdf_lines.json")
        >>> len(mapping)
        52
        >>> mapping[0]
        {"content": "While and If", "bbox": [51, 116, 154, 146]}
    """
    lines_path = Path(lines_json_path)

    if not lines_path.exists():
        raise FileNotFoundError(f"Lines JSON file not found: {lines_json_path}")

    try:
        with lines_path.open('r', encoding='utf-8') as f:
            lines_data = json.load(f)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in {lines_json_path}: {e}")

    if not isinstance(lines_data, list):
        raise ValueError(f"Expected list in {lines_json_path}, got {type(lines_data)}")

    sentence_mapping = []

    for item in lines_data:
        # Each item should have spans array
        spans = item.get('spans', [])
        if not spans:
            continue

        # Get the first span (each item typically has one span after merging)
        span = spans[0]
        content = span.get('content', '').strip()
        bbox = span.get('bbox', [])

        if not content:
            continue

        # Validate bbox format [x1, y1, x2, y2]
        if not isinstance(bbox, list) or len(bbox) != 4:
            logging.warning(f"Invalid bbox format for content: {content[:50]}...")
            continue

        sentence_mapping.append({
            'content': content,
            'bbox': bbox
        })

    logging.info(f"Generated sentence mapping with {len(sentence_mapping)} sentences from {lines_json_path}")
    return sentence_mapping


def update_file_extra_info_with_mapping(
    conn: sqlite3.Connection,
    file_uuid: str,
    sentence_mapping: List[Dict[str, Any]]
) -> None:
    """
    Update the extra_info column of a file record with sentence mapping.
    Merges with existing extra_info if present.

    Args:
        conn: SQLite database connection
        file_uuid: UUID of the file record to update
        sentence_mapping: List of {"content": str, "bbox": [...]} dicts
    """
    # Get current extra_info
    row = conn.execute("SELECT extra_info FROM file WHERE uuid=?", (file_uuid,)).fetchone()

    if not row:
        raise ValueError(f"File with uuid {file_uuid} not found in database")

    # Parse existing extra_info or create new dict
    extra_info_str = row[0]
    if extra_info_str:
        try:
            extra_info = json.loads(extra_info_str)
        except json.JSONDecodeError:
            logging.warning(f"Could not parse existing extra_info for {file_uuid}, creating new")
            extra_info = {}
    else:
        extra_info = {}

    # Add/update sentence_mapping
    extra_info['sentence_mapping'] = sentence_mapping

    # Update database
    updated_extra_info = json.dumps(extra_info, ensure_ascii=False)
    conn.execute(
        "UPDATE file SET extra_info=?, update_time=datetime('now', 'localtime') WHERE uuid=?",
        (updated_extra_info, file_uuid)
    )
    conn.commit()

    logging.info(f"Updated extra_info for file {file_uuid} with {len(sentence_mapping)} sentences")


def find_file_uuid(
    conn: sqlite3.Connection,
    file_name: str,
    course_code: str
) -> Optional[str]:
    """
    Find file UUID by file name and course code.

    Args:
        conn: SQLite database connection
        file_name: Name of the file (e.g., "disc01.pdf")
        course_code: Course code (e.g., "CS61A")

    Returns:
        File UUID if found, None otherwise
    """
    row = conn.execute(
        "SELECT uuid FROM file WHERE file_name=? AND course_code=?",
        (file_name, course_code)
    ).fetchone()

    if row:
        return row[0]
    return None


def add_sentence_mapping_to_file(
    db_path: str,
    lines_json_path: str,
    file_name: str,
    course_code: str
) -> bool:
    """
    Complete workflow to add sentence mapping to a file in the database.

    Args:
        db_path: Path to SQLite database
        lines_json_path: Path to lines JSON file
        file_name: Name of the PDF file
        course_code: Course code

    Returns:
        True if successful, False otherwise
    """
    try:
        # Generate mapping from JSON
        sentence_mapping = generate_sentence_mapping_from_json(lines_json_path)

        if not sentence_mapping:
            logging.error("No sentences found in JSON file")
            return False

        # Connect to database
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row

        # Find file record
        file_uuid = find_file_uuid(conn, file_name, course_code)

        if not file_uuid:
            logging.error(f"File not found in database: {file_name} (course: {course_code})")
            conn.close()
            return False

        # Update extra_info
        update_file_extra_info_with_mapping(conn, file_uuid, sentence_mapping)

        conn.close()
        logging.info(f"Successfully added sentence mapping for {file_name}")
        return True

    except Exception as e:
        logging.error(f"Error adding sentence mapping: {e}")
        return False
