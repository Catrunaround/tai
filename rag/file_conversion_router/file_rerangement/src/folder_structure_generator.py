#!/usr/bin/env python3
"""
Folder Structure Generator - Uses LLM to analyze course files and generate organized folder structure.

This module analyzes existing course files and uses an LLM to:
1. Determine how many folders should be created
2. Decide the folder structure (topics/units/modules)
3. Generate a syllabus.json file with the recommended structure
4. Optionally create the physical folder structure

USAGE:
    1. Edit the configuration dictionary in main() function (around line 474)
    2. Set your paths and options:
       - scan_dir: Directory containing course files to analyze
       - course_id: Course identifier (e.g., CS61A)
       - term: Academic term (e.g., 2025FA)
       - output: Path for syllabus.json
       - create_folders: Set to True to create folder structure
       - move_files: Set to True to move files into organized folders
       - dry_run: Set to True to preview without making changes
    3. Run: python folder_structure_generator.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Dict, Any, List

try:
    from dotenv import load_dotenv
    # Try multiple possible locations for .env file
    possible_env_paths = [
        Path(__file__).parent.parent / '.env',
        Path(__file__).parent.parent.parent / '.env',
        Path.cwd() / '.env',
        Path.cwd().parent / '.env',
    ]

    for env_path in possible_env_paths:
        if env_path.exists():
            load_dotenv(env_path)
            break
except ImportError:
    pass


FOLDER_STRUCTURE_PROMPT = """
You are an expert educational content organizer. Analyze the course files below and generate a TYPE-BASED folder organization system.

### Task
Students navigate by MATERIAL TYPE first (lectures, homeworks, labs), then by NUMBER.
- A student looking for "Lecture 5" goes to: Lectures/ → lecture_05/
- A student looking for "Homework 3" goes to: Homeworks/ → hw03/
- A student looking for "Lab 2" goes to: Labs/ → lab02/

Based on the file list, organize files by TYPE and NUMBER, NOT by topic.

### Course Information
Course ID: {course_id}
Term: {term}
Total Files: {file_count}

### File List
{file_list}

### Output Requirements
Generate a JSON object with this exact structure:

{{
  "course_id": "{course_id}",
  "term": "{term}",
  "structure_type": "type_based",
  "units": [
    {{
      "unit_id": "lectures",
      "title": "Lectures",
      "aliases": ["lecture", "lec", "slides", "01", "02", "03", "04", "..."],
      "description": "All lecture slides and materials organized by lecture number",
      "expected_types": ["lecture_slide", "code", "notes"],
      "suggested_files": ["assets/slides/01-Welcome_1pp/...", "assets/slides/02-.../..."]
    }},
    {{
      "unit_id": "homeworks",
      "title": "Homeworks",
      "aliases": ["hw", "homework", "assignment", "hw01", "hw02", "..."],
      "description": "All homework assignments organized by number",
      "expected_types": ["assignment", "code", "notes"],
      "suggested_files": [...]
    }},
    {{
      "unit_id": "labs",
      "title": "Labs",
      "aliases": ["lab", "lab01", "lab02", "..."],
      "description": "All lab exercises organized by number",
      "expected_types": ["lab", "code", "notes"],
      "suggested_files": [...]
    }}
  ]
}}

### Instructions - TYPE-BASED ORGANIZATION
Create folders by MATERIAL TYPE:
- **Lectures**: All lecture slides (slides/01, slides/02, etc.)
- **Homeworks**: All homework assignments (hw01, hw02, hw03, etc.)
- **Labs**: All lab materials (lab01, lab02, etc.)
- **Discussions**: Discussion worksheets and solutions (disc01, disc02, etc.)
- **Projects**: Major projects (hog, cats, ants, scheme, etc.)
- **Exams**: Exams and study guides (midterm, final, study guides)
- **Readings**: Course readings, textbooks, papers
- **Resources**: Other materials (syllabus, notes, etc.)

**aliases** should include:
- Type keywords: "lecture", "hw", "homework", "lab", "disc", "project", "exam"
- Number patterns: "01", "02", "03", "hw01", "lab02", "disc03", etc.
- Specific names: "hog", "cats", "ants", "scheme" for projects

**suggested_files**: Group ALL files of that type together

For large file sets (>300 files), you'll see a sample - identify all type patterns and extrapolate.

Output **only valid JSON** with no additional text or explanations.
"""


def scan_directory(directory: str | Path) -> List[Dict[str, str]]:
    """
    Scan a directory and return list of files with metadata.

    Returns:
        List of dicts with keys: name, path, extension, size_kb
    """
    directory = Path(directory)
    if not directory.exists() or not directory.is_dir():
        raise ValueError(f"Invalid directory: {directory}")

    files = []
    for file_path in directory.rglob("*"):
        if file_path.is_file():
            # Skip hidden files and system files
            if file_path.name.startswith('.'):
                continue

            files.append({
                "name": file_path.name,
                "path": str(file_path.relative_to(directory)),
                "extension": file_path.suffix,
                "size_kb": file_path.stat().st_size // 1024
            })

    return sorted(files, key=lambda x: x["name"])


def format_file_list(files: List[Dict[str, str]], max_files: int = 300) -> str:
    """
    Format file list for LLM prompt.

    For large file lists, provides a summary and representative sample.
    """
    if len(files) <= max_files:
        lines = []
        for f in files:
            lines.append(f"- {f['name']} ({f['extension']}, {f['size_kb']}KB) at {f['path']}")
        return "\n".join(lines)

    # For large file lists, provide statistics and samples
    from collections import Counter

    ext_counts = Counter(f['extension'] for f in files)

    summary = [
        f"TOTAL FILES: {len(files)} (showing representative sample)",
        f"\nFILE TYPE DISTRIBUTION:",
    ]

    for ext, count in ext_counts.most_common():
        summary.append(f"  {ext or '(no extension)'}: {count} files")

    summary.append(f"\n\nREPRESENTATIVE SAMPLE (first {max_files} files by name):")

    for f in files[:max_files]:
        summary.append(f"- {f['name']} ({f['extension']}, {f['size_kb']}KB) at {f['path']}")

    summary.append(f"\n... and {len(files) - max_files} more files")

    return "\n".join(summary)


def call_openai(prompt: str, model: str = "gpt-4o") -> str:
    """Call OpenAI API with JSON response format."""
    from openai import OpenAI

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not set in environment")

    client = OpenAI(api_key=api_key)

    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=16000,  # Increased for larger responses
            response_format={"type": "json_object"}
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        raise RuntimeError(f"OpenAI API call failed: {e}")


def extract_json(text: str) -> Dict[str, Any]:
    """Extract JSON from LLM response."""
    import re

    text = text.strip()

    # Try parsing as-is
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Extract from code block
    patterns = [
        r"```json\s*(\{.*?\})\s*```",
        r"```\s*(\{.*?\})\s*```",
    ]
    for pattern in patterns:
        m = re.search(pattern, text, flags=re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1))
            except json.JSONDecodeError:
                continue

    # Find first complete JSON object
    start = text.find('{')
    if start != -1:
        depth = 0
        for i in range(start, len(text)):
            if text[i] == '{':
                depth += 1
            elif text[i] == '}':
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start:i+1])
                    except json.JSONDecodeError:
                        pass
                    break

    raise ValueError(f"No valid JSON found in response. Preview: {text[:200]}...")


def move_files_to_folders(source_dir: str | Path, base_dir: str | Path, syllabus: Dict[str, Any], dry_run: bool = False) -> Dict[str, Any]:
    """
    Move files from source directory to organized folder structure based on syllabus.

    Args:
        source_dir: Source directory containing the files to organize
        base_dir: Base directory where organized folders are located
        syllabus: Syllabus JSON structure with file mappings
        dry_run: If True, only simulate file moves without actually moving files

    Returns:
        Dictionary containing file movement log with details of all operations
    """
    import shutil

    source_dir = Path(source_dir)
    base_dir = Path(base_dir)

    print(f"\n{'[DRY RUN] ' if dry_run else ''}Moving files to organized folders...")
    print("=" * 60)

    move_log = {
        "operation": "file_movement",
        "mode": "dry_run" if dry_run else "execute",
        "source_directory": str(source_dir),
        "base_directory": str(base_dir),
        "course_id": syllabus.get("course_id"),
        "term": syllabus.get("term"),
        "total_files_moved": 0,
        "total_files_failed": 0,
        "total_files_not_found": 0,
        "units": []
    }

    for unit in syllabus.get("units", []):
        unit_id = unit.get("unit_id", "U00")
        title = unit.get("title", "Untitled")
        folder_name = f"{title.replace(' ', '_').replace('/', '_')}"
        dest_folder = base_dir / folder_name

        unit_log = {
            "unit_id": unit_id,
            "folder_name": folder_name,
            "files_moved": 0,
            "files_failed": 0,
            "files_not_found": 0,
            "operations": []
        }

        suggested_files = unit.get("suggested_files", [])

        for file_rel_path in suggested_files:
            source_file = source_dir / file_rel_path

            # Preserve directory structure within unit folder
            dest_file = dest_folder / file_rel_path

            operation = {
                "source": str(source_file),
                "destination": str(dest_file),
                "status": None,
                "message": None
            }

            if not source_file.exists():
                operation["status"] = "not_found"
                operation["message"] = f"Source file does not exist"
                unit_log["files_not_found"] += 1
                move_log["total_files_not_found"] += 1

                if not dry_run:
                    print(f"  ⚠ Not found: {file_rel_path}")
            else:
                if dry_run:
                    operation["status"] = "planned"
                    operation["message"] = "Would move file"
                    unit_log["files_moved"] += 1
                    move_log["total_files_moved"] += 1
                else:
                    try:
                        # Create parent directories if needed
                        dest_file.parent.mkdir(parents=True, exist_ok=True)

                        # Copy file (use copy2 to preserve metadata)
                        shutil.copy2(source_file, dest_file)

                        operation["status"] = "success"
                        operation["message"] = "File moved successfully"
                        unit_log["files_moved"] += 1
                        move_log["total_files_moved"] += 1

                    except Exception as e:
                        operation["status"] = "failed"
                        operation["message"] = str(e)
                        unit_log["files_failed"] += 1
                        move_log["total_files_failed"] += 1
                        print(f"  ✗ Failed to move {file_rel_path}: {e}")

            unit_log["operations"].append(operation)

        # Print unit summary
        if dry_run:
            print(f"[DRY RUN] {folder_name}: Would move {unit_log['files_moved']} files")
        else:
            print(f"✓ {folder_name}: Moved {unit_log['files_moved']} files", end="")
            if unit_log["files_not_found"] > 0:
                print(f", {unit_log['files_not_found']} not found", end="")
            if unit_log["files_failed"] > 0:
                print(f", {unit_log['files_failed']} failed", end="")
            print()

        move_log["units"].append(unit_log)

    # Print final summary
    print("\n" + "=" * 60)
    if dry_run:
        print(f"[DRY RUN] Would move {move_log['total_files_moved']} files")
    else:
        print(f"✓ Successfully moved {move_log['total_files_moved']} files")
        if move_log['total_files_not_found'] > 0:
            print(f"⚠ {move_log['total_files_not_found']} files not found")
        if move_log['total_files_failed'] > 0:
            print(f"✗ {move_log['total_files_failed']} files failed to move")

    return move_log


def create_folder_structure(base_dir: str | Path, syllabus: Dict[str, Any], dry_run: bool = False) -> Dict[str, Any]:
    """
    Create physical folder structure based on syllabus JSON.

    Args:
        base_dir: Base directory where folders will be created
        syllabus: Syllabus JSON structure
        dry_run: If True, only print what would be created without actually creating folders

    Returns:
        Dictionary containing operations log with details of all actions
    """
    base_dir = Path(base_dir)

    print(f"\n{'[DRY RUN] ' if dry_run else ''}Creating folder structure in: {base_dir}")
    print("=" * 60)

    operations_log = {
        "operation": "folder_structure_creation",
        "mode": "dry_run" if dry_run else "execute",
        "base_directory": str(base_dir),
        "course_id": syllabus.get("course_id"),
        "term": syllabus.get("term"),
        "total_units": len(syllabus.get("units", [])),
        "folders": []
    }

    for unit in syllabus.get("units", []):
        unit_id = unit.get("unit_id", "U00")
        title = unit.get("title", "Untitled")

        # Create folder name: U01_Topic_Name
        folder_name = f"{unit_id}_{title.replace(' ', '_').replace('/', '_')}"
        folder_path = base_dir / folder_name

        folder_info = {
            "unit_id": unit_id,
            "folder_name": folder_name,
            "folder_path": str(folder_path),
            "title": title,
            "description": unit.get("description", ""),
            "aliases": unit.get("aliases", []),
            "expected_types": unit.get("expected_types", []),
            "suggested_files": unit.get("suggested_files", []),
            "file_count": len(unit.get("suggested_files", [])),
            "actions": []
        }

        if dry_run:
            print(f"[DRY RUN] Would create: {folder_path}")
            print(f"  Description: {unit.get('description', 'N/A')}")
            print(f"  Expected types: {', '.join(unit.get('expected_types', []))}")

            folder_info["actions"].append({
                "type": "create_directory",
                "path": str(folder_path),
                "status": "planned"
            })


            suggested_files = unit.get("suggested_files", [])
            if suggested_files:
                print(f"  Suggested files ({len(suggested_files)}):")
                for f in suggested_files[:5]:  # Show first 5
                    print(f"    - {f}")
                if len(suggested_files) > 5:
                    print(f"    ... and {len(suggested_files) - 5} more")
            print()
        else:
            try:
                folder_path.mkdir(parents=True, exist_ok=True)
                folder_info["actions"].append({
                    "type": "create_directory",
                    "path": str(folder_path),
                    "status": "success"
                })

                print(f"✓ Created: {folder_path}")

            except Exception as e:
                folder_info["actions"].append({
                    "type": "error",
                    "message": str(e),
                    "status": "failed"
                })
                print(f"✗ Failed to create: {folder_path} - {e}")

        operations_log["folders"].append(folder_info)

    if not dry_run:
        print(f"\n✓ Folder structure created successfully!")

    return operations_log


def main():
    # ========================================
    # CONFIGURATION - Edit these values
    # ========================================

    config = {
        # Required settings
        "scan_dir": "/Users/yyk956614/tai/rag/test_folder/cs61a_course_main",              # Directory containing course files to analyze
        "course_id": "CS61A",                             # Course ID (e.g., CS61A, EE106B)
        "term": "2025FA",                                 # Academic term (e.g., 2025FA, 2024SP)
        "output": "syllabus.json",                        # Output path for syllabus.json

        # Optional settings
        "model": "gpt-4.1",                                # OpenAI model to use
        "create_folders": True,                           # Create physical folder structure
        "output_dir": "/Users/yyk956614/tai/rag/test_folder",               # Directory where folders will be created
        "dry_run": False,                                 # Preview without creating folders
        "move_files": True,                               # Move files to organized folders
        "operations_log": None,                           # Custom path for operations log (None = auto)
        "move_log": None,                                 # Custom path for move log (None = auto)
    }

    # ========================================
    # Validation
    # ========================================

    if config["create_folders"] and not config["output_dir"]:
        print("Error: output_dir is required when create_folders is True", file=sys.stderr)
        sys.exit(1)
    if config["move_files"] and not config["create_folders"]:
        print("Error: move_files requires create_folders to be True", file=sys.stderr)
        sys.exit(1)

    # Convert config dict to object for compatibility with existing code
    class Args:
        def __init__(self, **entries):
            self.__dict__.update(entries)

    args = Args(**config)

    try:
        # Step 1: Scan directory
        print(f"Scanning directory: {args.scan_dir}")
        files = scan_directory(args.scan_dir)
        print(f"Found {len(files)} files")

        if len(files) == 0:
            print("Warning: No files found in directory", file=sys.stderr)
            sys.exit(1)

        # Step 2: Generate prompt and call LLM
        print(f"\nAnalyzing files with {args.model}...")
        file_list_text = format_file_list(files)
        prompt = FOLDER_STRUCTURE_PROMPT.format(
            course_id=args.course_id,
            term=args.term,
            file_count=len(files),
            file_list=file_list_text
        )

        response = call_openai(prompt, args.model)

        # Step 3: Extract and validate JSON
        print("Extracting structure from response...")
        syllabus = extract_json(response)

        # Validate structure
        if "units" not in syllabus or not isinstance(syllabus["units"], list):
            raise ValueError("Invalid syllabus structure: missing 'units' array")

        print(f"\n✓ Generated structure with {len(syllabus['units'])} units")

        # Step 4: Write syllabus JSON
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(syllabus, f, ensure_ascii=False, indent=2)

        print(f"✓ Wrote syllabus to: {output_path}")

        # Step 5: Create folders if requested
        operations_log = None
        if args.create_folders:
            operations_log = create_folder_structure(
                base_dir=args.output_dir,
                syllabus=syllabus,
                dry_run=args.dry_run
            )

            # Save operations log
            if args.operations_log:
                log_path = Path(args.operations_log)
            else:
                # Default: save in output directory or same as syllabus
                if args.output_dir:
                    log_path = Path(args.output_dir) / "operations_log.json"
                else:
                    log_path = output_path.parent / "operations_log.json"

            log_path.parent.mkdir(parents=True, exist_ok=True)

            with open(log_path, "w", encoding="utf-8") as f:
                json.dump(operations_log, f, ensure_ascii=False, indent=2)

            print(f"✓ Wrote operations log to: {log_path}")

        # Step 6: Move files if requested
        if args.move_files:
            move_log = move_files_to_folders(
                source_dir=args.scan_dir,
                base_dir=args.output_dir,
                syllabus=syllabus,
                dry_run=args.dry_run
            )

            # Save move log
            if args.move_log:
                move_log_path = Path(args.move_log)
            else:
                if args.output_dir:
                    move_log_path = Path(args.output_dir) / "move_log.json"
                else:
                    move_log_path = output_path.parent / "move_log.json"

            move_log_path.parent.mkdir(parents=True, exist_ok=True)

            with open(move_log_path, "w", encoding="utf-8") as f:
                json.dump(move_log, f, ensure_ascii=False, indent=2)

            print(f"✓ Wrote move log to: {move_log_path}")

        # Step 7: Print summary
        print("\n" + "=" * 60)
        print("SUMMARY")
        print("=" * 60)
        print(f"Course: {syllabus.get('course_id')} ({syllabus.get('term')})")
        print(f"Units: {len(syllabus.get('units', []))}")
        print("\nUnits created:")
        for i, unit in enumerate(syllabus.get("units", []), 1):
            print(f"  {i}. {unit.get('unit_id')}: {unit.get('title')}")
            print(f"     Files: {len(unit.get('suggested_files', []))}")

    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
