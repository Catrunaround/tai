from pathlib import Path
from textwrap import dedent
from openai.types.chat import ChatCompletionMessage
import json
from rag.file_conversion_router.post_processing.MarkdownProcessor.BaseMarkdownProcessor import MarkdownStructureBase

class VideoMarkdownStructure(MarkdownStructureBase):
    """Structures markdown files originating from video transcripts (mp4, mp3)."""
    def _get_structured_content(self) -> ChatCompletionMessage:
        with open(self.file_path, 'r', encoding='utf-8') as file:
            content = file.read()
        paragraph_count = content.count('\n\n') + 1
        if not content.strip(): raise ValueError("The content is empty or not properly formatted.")
        file_name = self.file_path.name
        response = self.client.chat.completions.create(
            model="gpt-4.1",
            messages=[
                {
                    "role": "system",
                    "content": dedent(f"""
                                        You are an expert AI assistant specializing in analyzing and structuring educational material. You will be given markdown content from a video in the course "{self.course_name}", from the file "{file_name}". The text is already divided into paragraphs.
                                        Your task is to perform the following actions and format the output as a single JSON object:
                                        1.  **Group into Sections:** Analyze the entire text and divide it into **at most 5 logical sections**.
                                        2.  **Generate Titles:**
                                            - For each **section**, create a concise and descriptive title.
                                            - For each **original paragraph**, create an engaging title that reflects its main topic.
                                        3.  **Create a Nested Structure:** The JSON output must have a `sections` array.
                                            - Each element in the `sections` array is an object representing one section.
                                            - **Crucially, each section object must contain its own `paragraphs` array.** This nested array should list all the paragraphs that belong to that section.
                                            - Each paragraph object within the nested array must include its title and its **original index** from the source text (starting from 1).
                                        ### Part 2: Extract Key Concepts
                                        Your goal is to identifying and explaining the key concepts in each section to help a student recap the material.
                                        For each Key Concept, provide the following information:
                                       - **Key Concept:** A descriptive phrase or sentence that clearly captures the main idea
                                       - **Source Section:** The specific section title(s) in the material where this concept is discussed
                                       - **Content Coverage:** List only the aspects that the section actually explained with aspect and content. 
                                         - Some good examples of aspect: Definition, How it works, What happened, Why is it important, etc
                                         - The content also should be from the section.
                                        """)
                },
                {
                    "role": "user",
                    "content": f"{content} "
                }
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "course_content_knowledge_sorting",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "properties": {
                            "paragraphs": {
                                "type": "array",
                                "minItems": paragraph_count,
                                "maxItems": paragraph_count,
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "title": {"type": "string"},
                                        "paragraph_index" : {"type": "integer"}
                                    },
                                    "required": ["title", "paragraph_index"],
                                    "additionalProperties": False
                                }
                            },
                            "sections": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "minItems": 5,
                                    "properties": {
                                        "section_title": {"type": "string"},
                                        "start_paragraph_index": {"type": "integer","description": "The 1-based index from the 'paragraphs' array where this section begins.",
                                                                  "minimum": 1,
                                                                  "maximum": paragraph_count}
                                    },
                                    "required": ["section_title", "start_paragraph_index"],
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
                                                    "aspect" : {"type": "string"},
                                                    "content" : {"type": "string"}
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
                        "required": ["paragraphs","sections", "key_concepts"],
                        "additionalProperties": False
                    }
                }
            },
        )
        messages = response.choices[0].message
        data = messages.content
        content_dict = json.loads(data)
        return content_dict

    def _apply_structure_to_markdown(self, data, output_path: Path):
        original_content = self.file_path.read_text(encoding='utf-8')
        original_paragraphs = [p.strip() for p in original_content.split('\n\n') if p.strip()]
        md_parts = []
        section_starts = {s['start_paragraph_index']: s['section_title'] for s in data.get('sections')}
        for paragraph in sorted(data['paragraphs'], key=lambda p: p['paragraph_index']):
            p_index = paragraph['paragraph_index']
            p_title = paragraph['title']
            if p_index in section_starts:
                section_title = section_starts[p_index]
                md_parts.append(f"# {section_title}\n\n")
            md_parts.append(f"## {p_title}\n\n")
            content_index = p_index - 1
            if 0 <= content_index < len(original_paragraphs):
                md_parts.append(f"{original_paragraphs[content_index]}\n\n")
            else:
                md_parts.append(f"[Content for paragraph {p_index} not found]\n\n")

        output_content = "".join(md_parts)
        output_path.write_text(output_content, encoding='utf-8')

        return output_content