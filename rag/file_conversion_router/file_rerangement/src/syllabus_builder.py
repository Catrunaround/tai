#!/usr/bin/env python3  
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import List, Dict, Any

# Load environment variables from .env file
try:
    from dotenv import load_dotenv
    # Try multiple possible locations for .env file
    possible_env_paths = [
        Path(__file__).parent.parent / '.env',  # file_conversion_router/.env
        Path(__file__).parent.parent.parent / '.env',  # rag/.env
        Path.cwd() / '.env',  # current working directory
        Path.cwd().parent / '.env',  # parent of current working directory
    ]
    
    env_loaded = False
    for env_path in possible_env_paths:
        if env_path.exists():
            load_dotenv(env_path)
            print(f"Loaded environment variables from: {env_path}")
            env_loaded = True
            break
    
    if not env_loaded:
        print("Warning: No .env file found in expected locations", file=sys.stderr)
        
except ImportError:
    # If python-dotenv is not available, continue without it
    print("Warning: python-dotenv not available, environment variables not loaded", file=sys.stderr)

ALLOWED_TYPES = {
    "lecture_slide","reading","assignment","lab","project","notes","exam","code","media"
}

PROMPT_TEMPLATE = r"""
You are an expert educational content organizer. Your job is to analyze the course syllabus and generate a TYPE-BASED organization structure that helps students find materials easily.

### Task
Students navigate by MATERIAL TYPE first (Lectures, Homeworks, Labs), NOT by topic.
- A student looking for "Lecture 5" goes to: Lectures/ → lecture_05/
- A student looking for "Homework 3" goes to: Homeworks/ → hw03/
- A student looking for "Lab 2" goes to: Labs/ → lab02/

Based on the syllabus, identify what types of materials exist and how they are numbered/organized.

### JSON Schema
Generate a JSON object with this exact structure:

{{
  "course_id": "{course_id}",
  "term": "{term}",
  "structure_type": "type_based",
  "units": [
    {{
      "unit_id": "lectures",
      "title": "Lectures",
      "aliases": ["lecture", "lec", "slides", "01", "02", "03", "..."],
      "description": "All lecture slides and materials organized by lecture number",
      "expected_types": ["lecture_slide", "code", "notes"]
    }},
    {{
      "unit_id": "homeworks",
      "title": "Homeworks",
      "aliases": ["hw", "homework", "assignment", "hw01", "hw02", "..."],
      "description": "All homework assignments organized by number",
      "expected_types": ["assignment", "code", "notes"]
    }},
    {{
      "unit_id": "labs",
      "title": "Labs",
      "aliases": ["lab", "lab01", "lab02", "..."],
      "description": "All lab exercises organized by number",
      "expected_types": ["lab", "code", "notes"]
    }}
  ]
}}

### Organization Rules - TYPE-BASED STRUCTURE
Create units by MATERIAL TYPE based on what you find in the syllabus:

**Common Unit Types:**
- **Lectures**: All lecture slides/recordings (numbered: 01, 02, 03, etc.)
- **Homeworks**: Homework assignments (hw01, hw02, hw03, etc.)
- **Labs**: Lab exercises (lab01, lab02, etc.)
- **Discussions**: Discussion worksheets (disc01, disc02, etc.)
- **Projects**: Major projects (may have names like "hog", "cats", or just project1, project2)
- **Exams**: Exams and study materials (midterm, final, practice exams)
- **Readings**: Course readings, textbooks, papers
- **Resources**: Syllabus, course policies, general notes

**For each unit:**
- **unit_id**: lowercase identifier (e.g., "lectures", "homeworks", "labs")
- **title**: Student-friendly name (e.g., "Lectures", "Homeworks")
- **aliases**: Include type keywords + number patterns from syllabus
  - Type keywords: "lecture", "hw", "homework", "lab", "disc", "project", "exam"
  - Number patterns: extract from syllabus (e.g., "01", "02", "hw01", "lab02")
  - Project names: if mentioned (e.g., "hog", "cats", "ants")
- **description**: Brief explanation of what materials are in this unit
- **expected_types**: CRITICAL - Be precise and specific. Follow the mapping below:

### Expected Types Mapping (FOLLOW STRICTLY)
Choose expected_types based ONLY on what materials are PRIMARY to that unit type:

**lectures** → ["lecture_slide"] OR ["lecture_slide", "media"] if recordings mentioned
  - Add "code" only if lecture demos/notebooks explicitly mentioned
  - Do NOT add "notes" (notes are separate supplementary materials)

**homeworks** → ["assignment"]
  - Add "code" only if starter code/autograder mentioned
  - Do NOT add "notes" or "lecture_slide"

**labs** → ["lab"]
  - Add "code" only if lab starter code mentioned
  - Do NOT add "notes" or "assignment"

**discussions** → ["notes"]
  - "notes" means discussion worksheets/handouts
  - Do NOT add "assignment" or "lecture_slide"

**projects** → ["project"]
  - Add "code" if starter code/frameworks mentioned
  - Do NOT add "assignment" or "lab"

**exams** → ["exam"]
  - ONLY "exam" - this includes practice exams, past exams, exam PDFs
  - Do NOT add "notes" (study guides are separate)
  - Do NOT add "reading" or other types

**readings** → ["reading"]
  - Textbook chapters, papers, articles, book PDFs
  - Do NOT add "lecture_slide" or "notes"

**resources** → ["notes"]
  - Syllabus, policies, general reference materials
  - Can add "reading" if supplementary materials mentioned

**Rule**: Each unit should have 1-3 expected_types maximum. Be conservative and specific.

### Extraction Guidelines
1. **Read the syllabus carefully** to identify all material types mentioned
2. **Extract numbering patterns** (e.g., if syllabus shows "HW 1-10", add hw01-hw10 to aliases)
3. **Look for project names** (e.g., "Project: Hog Game" → add "hog" to aliases)
4. **Identify exam types** (midterm, final, practice exams mentioned?)
5. **Check for readings** (textbook chapters, papers, articles?)

### Output Requirements
- Output **only valid JSON** with no extra commentary
- Keys must match schema exactly
- Use lowercase for unit_id
- Include 3-8 units (only types that make sense for this course)
- Aliases should be comprehensive but concise (<40 characters each)
- Valid expected_types: ["lecture_slide","reading","assignment","lab","project","notes","exam","code","media"]

### Course Metadata
course_id = "{course_id}"
term = "{term}"

### Raw Syllabus Text
<<<RAW_SYLLABUS_START
{raw_text}
RAW_SYLLABUS_END
"""

def preprocess_markdown(md_text: str) -> str:
    """
    Preprocess markdown to extract clean text suitable for LLM processing.
    Removes excessive formatting while preserving structure.
    """
    # Remove HTML comments
    text = re.sub(r'<!--.*?-->', '', md_text, flags=re.DOTALL)

    # Convert headers to plain text with proper spacing
    text = re.sub(r'^#{1,6}\s+', '\n', text, flags=re.MULTILINE)

    # Remove image references but keep alt text
    text = re.sub(r'!\[([^\]]*)\]\([^\)]+\)', r'\1', text)

    # Convert links to plain text (keep link text, discard URL)
    text = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', text)

    # Remove inline code backticks
    text = re.sub(r'`([^`]+)`', r'\1', text)

    # Remove code blocks
    text = re.sub(r'```.*?```', '', text, flags=re.DOTALL)

    # Remove horizontal rules
    text = re.sub(r'^[-*_]{3,}$', '', text, flags=re.MULTILINE)

    # Normalize whitespace
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r'[ \t]+', ' ', text)

    return text.strip()

def extract_json(text: str) -> Dict[str, Any]:
    """
    Extract JSON from LLM output with multiple fallback strategies.
    Handles markdown code blocks, plain JSON, and embedded JSON.
    """
    text = text.strip()

    # Strategy 1: Try parsing as-is
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Strategy 2: Extract from markdown JSON code block
    patterns = [
        r"```json\s*(\{.*?\})\s*```",  # ```json {...} ```
        r"```\s*(\{.*?\})\s*```",       # ``` {...} ```
    ]
    for pattern in patterns:
        m = re.search(pattern, text, flags=re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1))
            except json.JSONDecodeError:
                continue

    # Strategy 3: Find first complete JSON object
    start = text.find('{')
    if start != -1:
        # Count braces to find matching closing brace
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

    # Strategy 4: Last resort - find outermost braces
    end = text.rfind('}')
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start:end+1])
        except json.JSONDecodeError:
            pass

    raise ValueError(f"No valid JSON found in model output. Output preview: {text[:200]}...")

def normalize_json(obj: Dict[str, Any], course_id: str, term: str) -> Dict[str, Any]:
    obj["course_id"] = course_id
    obj["term"] = term
    obj["structure_type"] = "type_based"

    units = obj.get("units") or []
    if not isinstance(units, list):
        units = []
    if len(units) < 3:
        print("[warn] fewer than 3 units; consider improving the prompt", file=sys.stderr)
    if len(units) > 8:
        print(f"[warn] more than 8 units ({len(units)}), truncating to 8", file=sys.stderr)
        units = units[:8]

    normalized = []
    for i, u in enumerate(units, 1):
        n = {}
        # Keep original unit_id (e.g., "lectures", "homeworks") instead of renumbering
        unit_id = u.get("unit_id", "").strip().lower()
        if not unit_id:
            unit_id = f"unit_{i}"
        n["unit_id"] = unit_id

        n["title"] = (u.get("title") or "Untitled").strip()
        aliases = [a.strip() for a in u.get("aliases", []) if isinstance(a, str) and len(a.strip()) < 40]
        seen = set()
        aliases = [a for a in aliases if not (a.lower() in seen or seen.add(a.lower()))]
        n["aliases"] = aliases[:15]
        desc = u.get("description") or ""
        n["description"] = desc.strip()
        et = [t for t in u.get("expected_types", []) if t in ALLOWED_TYPES]
        if not et:
            et = ["lecture_slide", "notes"]
        n["expected_types"] = et[:6]
        normalized.append(n)

    obj["units"] = normalized
    return obj

def call_openai(prompt: str, model: str, api_key: str | None = None) -> str:
    """
    Call OpenAI API with the given prompt.
    Uses chat completions API (correct endpoint).
    """
    from openai import OpenAI
    api_key = api_key or os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not set")

    client = OpenAI(api_key=api_key)

    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=4000,
            response_format={"type": "json_object"}  # Request JSON output
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        raise RuntimeError(f"OpenAI API call failed: {e}")

def validate_input_file(file_path: str) -> str:
    """
    Validate and read input file.
    Supports .md, .txt, and plain text files.
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Input file not found: {file_path}")

    if not path.is_file():
        raise ValueError(f"Input path is not a file: {file_path}")

    # Check file extension
    if path.suffix.lower() not in ['.md', '.txt', '.markdown', '']:
        print(f"[warn] Unexpected file extension '{path.suffix}'. Expected .md or .txt", file=sys.stderr)

    return path.read_text(encoding="utf-8")

def main():
    ap = argparse.ArgumentParser(
        description="Generate type-based syllabus.json from course syllabus file. Organizes materials by type (Lectures, Homeworks, Labs) rather than topics.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Example usage:
  python syllabus_builder.py --in syllabus.md --out syllabus.json --course-id EE106B --term 2025FA
  python syllabus_builder.py --in syllabus.txt --out output.json --course-id CS61A --term 2024SP --model gpt-4o

Output structure:
  {
    "course_id": "CS61A",
    "term": "2025FA",
    "structure_type": "type_based",
    "units": [
      {"unit_id": "lectures", "title": "Lectures", "aliases": ["lecture", "lec", "01", "02", ...], ...},
      {"unit_id": "homeworks", "title": "Homeworks", "aliases": ["hw", "homework", "hw01", ...], ...},
      {"unit_id": "labs", "title": "Labs", "aliases": ["lab", "lab01", "lab02", ...], ...}
    ]
  }
        """
    )
    ap.add_argument("--in", dest="inp", required=True, help="Input markdown/text file path")
    ap.add_argument("--out", dest="out", required=True, help="Output JSON file path")
    ap.add_argument("--course-id", dest="course_id", required=True, help="Course ID (e.g., EE106B, CS61A)")
    ap.add_argument("--term", required=True, help="Term (e.g., 2025FA, 2024SP)")
    ap.add_argument("--model", default="gpt-4o", help="OpenAI model to use (default: gpt-4o)")
    ap.add_argument("--skip-preprocess", action="store_true", help="Skip markdown preprocessing")
    args = ap.parse_args()

    try:
        # Read and validate input
        print(f"Reading input file: {args.inp}")
        raw = validate_input_file(args.inp)

        # Preprocess markdown if needed
        if not args.skip_preprocess and Path(args.inp).suffix.lower() in ['.md', '.markdown']:
            print("Preprocessing markdown to clean text...")
            raw = preprocess_markdown(raw)

        # Generate prompt and call OpenAI
        print(f"Calling OpenAI API (model: {args.model})...")
        prompt = PROMPT_TEMPLATE.format(
            course_id=args.course_id,
            term=args.term,
            raw_text=raw
        )
        text = call_openai(prompt, args.model)

        # Extract and normalize JSON
        print("Extracting JSON from response...")
        obj = extract_json(text)
        obj = normalize_json(obj, args.course_id, args.term)

        # Write output
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)

        print(f"✓ Successfully wrote {args.out} with {len(obj.get('units', []))} material types.")
        print(f"  Structure type: type_based")
        print(f"  Material types: {', '.join([u.get('unit_id', '') for u in obj.get('units', [])])}")

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
