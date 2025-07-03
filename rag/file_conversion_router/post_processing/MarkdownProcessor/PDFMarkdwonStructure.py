import json
import re
from pathlib import Path
from textwrap import dedent
from openai.types.chat import ChatCompletionMessage

from rag.file_conversion_router.post_processing.MarkdownProcessor.BaseMarkdownProcessor import MarkdownStructureBase


class PdfMarkdownStructure(MarkdownStructureBase):
    """Structures markdown files originating from PDFs."""

    def _get_structured_content(self) -> ChatCompletionMessage:
        self._remove_redundant_title()
        with open(self.file_path, 'r', encoding='utf-8') as file:
            content = file.read()
        if not content.strip(): raise ValueError("The content is empty or not properly formatted.")
        file_name = self.file_path.name
        title_list = self.get_title_list()
        response = self.client.chat.completions.create(
            model="gpt-4.1",
            messages=[
                {
                    "role": "system",
                    "content": dedent(f"""
                    You are an expert AI assistant for structuring educational material. You will be given markdown content from the file "{file_name}" for the course "{self.course_name}".
                    Your task is to analyze this content and produce a structured JSON output. The task has two parts: title structuring and key concept extraction.
                    ### Part 1: Correct Title Hierarchy
                    **Your Goal:** The markdown's title hierarchy is likely flat (e.g., every title starts with a single '#'). Your job is to determine the correct semantic level for each of these titles.
                    **Crucial Rule:**
                    - A line is considered a title if, and only if, it begins with one or more '#' characters in the provided text. Do NOT invent new titles or treat any other text as a title.
                    **How to Determine the Correct Level (1, 2, 3, etc.):**
                    1.  **Analyze Logical Structure:** Read the titles in sequence to understand the flow of the document. A title that introduces a new, major section is a high level (e.g., level 1). A title that discusses a sub-point of the previous title is a lower level (e.g., level 2 or 3).
                    2.  **Preserve Order:** The titles in your JSON output must be in the exact same order they appear in the source text.
                    3.  **Output Format:** In the JSON, provide the clean title text (without the '#') and the integer level you have assigned.

                    ### Part 2: Extract Key Concepts
                    Your goal is to identifying and explaining the key concepts in each level 1 title to help a student recap the material.
                    For each Key Concept, provide the following information:
                   - **Key Concept:** A descriptive phrase or sentence that clearly captures the main idea
                   - **Source Section:** The specific level 1 title(s) in the material where this concept is discussed
                   - **Content Coverage:** List only the aspects that the section actually explained with aspect and content. 
                     - Some good examples of aspect: Definition, How it works, What happened, Why is it important, etc
                     - The content also should be from the sections.
                    """)
                },
                {
                    "role": "user",
                    "content": f"{content}"
                }
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "course_content_knowledge_sorting",
                    "strict": True,
                    "description": "Structures course content into titles and key concept.",
                    "schema": {
                        "type": "object",
                        "properties": {
                            "titles_with_levels": {
                                "type": "array",
                                "description": "A list of titles with their inferred hierarchical level, preserving the original order.",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "title": {"type": "string",
                                                  "enum": title_list },

                                        "level_of_title": {"type": "integer",
                                                           "description": "The inferred hierarchy level (e.g., 1, 2, 3)."}
                                    },
                                    "required": ["title", "level_of_title"],
                                    "additionalProperties": False
                                }
                            },
                            "key_concepts": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "concepts": {"type": "string"},
                                        "source_section_title": {"type": "string"},
                                        "content_coverage": {
                                            "type": "array",
                                            "items": {
                                                "type": "object",
                                                "properties": {
                                                    "aspect": {"type": "string"},
                                                    "content": {"type": "string"}
                                                },
                                                "required": ["aspect", "content"],
                                                "additionalProperties": False
                                            }
                                        }
                                    },
                                    "required": ["concepts", "source_section_title", "content_coverage"],
                                    "additionalProperties": False
                                }
                            }
                        },
                        "required": ["titles_with_levels", "key_concepts"],
                        "additionalProperties": False
                    },
                }
            },
        )
        messages = response.choices[0].message
        data = messages.content
        content_dict = json.loads(data)
        return content_dict

    def get_title_list(self):
        with open(self.file_path) as f:
            contents = f.read()
        lines = contents.split("\n")
        titles = []
        for line in lines:
            if line.startswith("#"):
                line = line[1:]
                titles.append(line)
        return titles

    def _apply_structure_to_markdown(self, json_dict, output_path: Path):
        mapping_list = json_dict.get('titles_with_levels')
        title_level_map = {item['title'].strip(): int(item['level_of_title']) for item in mapping_list}
        lines = self.file_path.read_text(encoding='utf-8').splitlines(keepends=True)
        title_pattern = re.compile(r'^(?P<hashes>#+)\s*(?P<title>.+?)\s*$')
        new_lines = []
        for line in lines:
            match = title_pattern.match(line)
            if match:
                raw_title = match.group('title').strip()
                if raw_title in title_level_map:
                    new_level = title_level_map[raw_title]
                    new_lines.append(f"{'#' * new_level} {raw_title}\n")
                    continue
            new_lines.append(line)
        output_path.write_text(''.join(new_lines), encoding='utf-8')
        print(f"✅ Rewrote markdown with corrected title levels to: {output_path}")

    def _remove_redundant_title(self) -> bool:
        normalized_filename = self.file_path.stem.lower().replace('-', ' ').replace('_', ' ')
        try:
            with open(self.file_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
        except FileNotFoundError:
            return False
        if not lines: return False
        first_line = lines[0]
        if first_line.startswith('# '):
            title_text = first_line.lstrip('# ').strip()
            if normalized_filename == title_text.lower():
                print(f"Found and removing redundant title in '{self.file_path.name}'.")
                remaining_lines = lines[1:]
                while remaining_lines and remaining_lines[0].strip() == '': remaining_lines.pop(0)
                heading_levels_found = set()
                for line in remaining_lines:
                    stripped_line = line.lstrip()
                    if stripped_line.startswith('#'):
                        level = 0
                        while level < len(stripped_line) and stripped_line[level] == '#':
                            level += 1
                        heading_levels_found.add(level)

                final_lines_to_write = []
                if len(heading_levels_found) > 1:
                    print("Multiple heading levels found. Promoting subsequent headings by one level.")
                    for line in remaining_lines:
                        stripped_line = line.lstrip()
                        if stripped_line.startswith('##'):
                            first_hash_index = line.find('#')
                            new_line = line[:first_hash_index] + line[first_hash_index + 1:]
                            final_lines_to_write.append(new_line)
                        else:
                            final_lines_to_write.append(line)
                else:
                    print("No promotion needed (headings are uniform or absent).")
                    final_lines_to_write = remaining_lines
                with open(self.file_path, 'w', encoding='utf-8') as f:
                    f.write("".join(final_lines_to_write))
                return True

        print(f"No redundant title found in '{self.file_path.name}'.")
        return False