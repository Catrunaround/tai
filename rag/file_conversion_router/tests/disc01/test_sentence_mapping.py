#!/usr/bin/env python3
"""
Test script to verify sentence mapping functionality.
Creates a test database, adds a file record, and tests sentence mapping.
"""

import sys
import json
import sqlite3
from pathlib import Path

# Add parent directories to path
test_dir = Path(__file__).parent
sys.path.insert(0, str(test_dir.parent.parent))

from file_conversion_router.services.sentence_mapping_service import (
    add_sentence_mapping_to_file,
    generate_sentence_mapping_from_json
)

# SQL to initialize database (copied to avoid import dependencies)
SQL_INIT = """
PRAGMA foreign_keys=ON;
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;

CREATE TABLE IF NOT EXISTS file (
  uuid         TEXT PRIMARY KEY,
  file_hash    TEXT NOT NULL UNIQUE,
  sections     TEXT,
  relative_path TEXT,
  course_code  TEXT,
  course_name  TEXT,
  file_name    TEXT,
  extra_info   TEXT,
  url          TEXT,
  vector       BLOB,
  created_at TIMESTAMP DEFAULT (datetime('now', 'localtime')),
  update_time TIMESTAMP DEFAULT (datetime('now', 'localtime'))
);
"""


def create_test_database(db_path: Path) -> sqlite3.Connection:
    """Create a test database with the file table."""
    if db_path.exists():
        db_path.unlink()

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.executescript(SQL_INIT)
    return conn


def insert_test_file_record(conn: sqlite3.Connection, file_uuid: str, file_name: str, course_code: str):
    """Insert a test file record."""
    conn.execute("""
        INSERT INTO file (uuid, file_hash, sections, relative_path, course_code, course_name, file_name)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        file_uuid,
        'test_hash_123',
        '[]',
        f'tests/disc01/{file_name}',
        course_code,
        'Test Course',
        file_name
    ))
    conn.commit()
    print(f"✓ Inserted test file record: {file_name}")


def verify_sentence_mapping(conn: sqlite3.Connection, file_uuid: str) -> bool:
    """Verify that sentence mapping was added correctly."""
    row = conn.execute("SELECT extra_info FROM file WHERE uuid=?", (file_uuid,)).fetchone()

    if not row:
        print("✗ File record not found")
        return False

    extra_info_str = row[0]
    if not extra_info_str:
        print("✗ No extra_info found")
        return False

    try:
        extra_info = json.loads(extra_info_str)
    except json.JSONDecodeError as e:
        print(f"✗ Failed to parse extra_info: {e}")
        return False

    if 'sentence_mapping' not in extra_info:
        print("✗ No sentence_mapping in extra_info")
        return False

    sentence_mapping = extra_info['sentence_mapping']

    if not isinstance(sentence_mapping, list):
        print(f"✗ sentence_mapping is not a list: {type(sentence_mapping)}")
        return False

    if len(sentence_mapping) == 0:
        print("✗ sentence_mapping is empty")
        return False

    # Verify structure of first item
    first_item = sentence_mapping[0]
    if 'content' not in first_item or 'bbox' not in first_item:
        print(f"✗ Invalid structure: {first_item}")
        return False

    if not isinstance(first_item['bbox'], list) or len(first_item['bbox']) != 4:
        print(f"✗ Invalid bbox format: {first_item['bbox']}")
        return False

    print(f"✓ Sentence mapping verified: {len(sentence_mapping)} sentences")
    print(f"  First sentence: {first_item['content'][:60]}...")
    print(f"  First bbox: {first_item['bbox']}")
    return True


def main():
    print("=" * 70)
    print("Testing Sentence Mapping Functionality")
    print("=" * 70)

    # Setup paths
    test_dir = Path(__file__).parent
    db_path = test_dir / "test_metadata.db"
    lines_json_path = test_dir / "disc01.pdf_lines.json"
    file_name = "disc01.pdf"
    course_code = "CS61A"
    file_uuid = "test-uuid-12345"

    print(f"\nTest files:")
    print(f"  Database: {db_path}")
    print(f"  Lines JSON: {lines_json_path}")
    print(f"  File: {file_name}")
    print(f"  Course: {course_code}")

    # Step 1: Create test database
    print("\n[Step 1] Creating test database...")
    conn = create_test_database(db_path)

    # Step 2: Insert test file record
    print("\n[Step 2] Inserting test file record...")
    insert_test_file_record(conn, file_uuid, file_name, course_code)
    conn.close()

    # Step 3: Test sentence mapping generation
    print("\n[Step 3] Generating sentence mapping from JSON...")
    sentence_mapping = generate_sentence_mapping_from_json(str(lines_json_path))
    print(f"✓ Generated {len(sentence_mapping)} sentences")

    # Step 4: Add sentence mapping to database
    print("\n[Step 4] Adding sentence mapping to database...")
    success = add_sentence_mapping_to_file(
        db_path=str(db_path),
        lines_json_path=str(lines_json_path),
        file_name=file_name,
        course_code=course_code
    )

    if not success:
        print("✗ Failed to add sentence mapping")
        return 1

    # Step 5: Verify the mapping
    print("\n[Step 5] Verifying sentence mapping in database...")
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    if not verify_sentence_mapping(conn, file_uuid):
        print("\n✗ Verification failed!")
        conn.close()
        return 1

    # Step 6: Print sample sentences
    print("\n[Step 6] Sample sentences from mapping:")
    row = conn.execute("SELECT extra_info FROM file WHERE uuid=?", (file_uuid,)).fetchone()
    extra_info = json.loads(row[0])
    sentences = extra_info['sentence_mapping']

    for i in range(min(5, len(sentences))):
        sent = sentences[i]
        content_preview = sent['content'][:80] + "..." if len(sent['content']) > 80 else sent['content']
        print(f"  [{i}] {content_preview}")
        print(f"      bbox: {sent['bbox']}")

    conn.close()

    print("\n" + "=" * 70)
    print("✓ All tests passed!")
    print("=" * 70)
    print(f"\nTest database created at: {db_path}")
    print("You can inspect it with: sqlite3 test_metadata.db")

    return 0


if __name__ == '__main__':
    sys.exit(main())
