from file_conversion_router.conversion.base_converter import BaseConverter
from pathlib import Path
import base64
import json
import os
import re

from loguru import logger
from file_conversion_router.utils.artifact_helpers import (
    json_attachment,
    binary_attachment,
    iter_image_files,
)


class PdfConverter(BaseConverter):
    def __init__(self, course_name, course_code, file_uuid: str = None):
        super().__init__(course_name, course_code, file_uuid)
        self.available_tools = ["MinerU"]
        self.index_helper = None
        self.file_name = ""
        self.use_remote_vlm_descriptions = True

    def describe_image_with_vlm(self, image_path: Path) -> str:
        """Call OpenAI VLM to get a text description of an image."""
        try:
            from openai import OpenAI
            client = OpenAI()
            with open(image_path, "rb") as f:
                image_data = base64.b64encode(f.read()).decode("utf-8")
            ext = image_path.suffix.lstrip(".").lower()
            mime = "image/jpeg" if ext in ("jpg", "jpeg") else f"image/{ext}"
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{mime};base64,{image_data}"},
                        },
                        {
                            "type": "text",
                            "text": (
                                "Describe this image from an educational document. "
                                "Focus on any code, diagrams, tables, formulas, or key visual content. "
                                "Be concise but complete."
                            ),
                        },
                    ],
                }],
                max_tokens=500,
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            logger.warning(f"VLM description failed for {image_path}: {e}")
            return ""

    def replace_images_with_vlm_descriptions(self, content: str, images_dir: Path) -> str:
        """Replace markdown image links with VLM-generated text descriptions."""
        pattern = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")

        def replace_match(m):
            img_filename = Path(m.group(2)).name
            img_path = images_dir / img_filename
            if img_path.exists():
                desc = self.describe_image_with_vlm(img_path)
                if desc:
                    return f"\n\n**[Image]** {desc}\n\n"
            return ""

        return pattern.sub(replace_match, content)

    def clean_markdown_content(self, markdown_path, images_dir: Path = None):
        with open(markdown_path, "r", encoding="utf-8") as file:
            content = file.read()

        if (
            getattr(self, "use_remote_vlm_descriptions", True)
            and images_dir is not None
            and images_dir.exists()
            and os.getenv("OPENAI_API_KEY")
        ):
            content = self.replace_images_with_vlm_descriptions(content, images_dir)
        else:
            content = re.sub(r"!\[.*?\]\(.*?\)", "", content)

        content = re.sub(r'^[ #]+$', '-------------', content, flags=re.MULTILINE)

        with open(markdown_path, "w", encoding="utf-8") as file:
            file.write(content)
        return content

    # Override
    def _to_markdown(
        self, input_path: Path, output_path: Path, conversion_method: str = "MinerU"
    ) -> Path:
        self.file_name = input_path.name
        output_dir = output_path.parent

        if conversion_method == "MinerU":
            from file_conversion_router.services.tai_MinerU_service.api import convert_pdf_to_md_by_MinerU
            md_file_path = convert_pdf_to_md_by_MinerU(input_path, output_dir)

            if md_file_path.exists():
                print(f"Markdown file found: {md_file_path}")
            else:
                raise FileNotFoundError(f"Markdown file not found: {md_file_path}")

            target = md_file_path
            # images_dir: e.g. output_dir/lecture.pdf_images/
            images_dir = output_dir / f"{md_file_path.stem}_images"
            cleaned_content = self.clean_markdown_content(target, images_dir)
            json_file_path = md_file_path.with_name(f"{md_file_path.stem}_content_list.json")
            if json_file_path.exists():
                with open(json_file_path, "r", encoding="utf-8") as f_json:
                    data = json.load(f_json)
            else:
                logger.warning(f"content_list.json not found at {json_file_path}, skipping index generation")
                data = []
            self.generate_index_helper(data, md=cleaned_content)
            return target

    def collect_artifacts(
        self,
        base_dir: Path,
        input_path: Path,
        include_binary_attachments: bool = False,
    ) -> tuple[dict, list[Path]]:
        attachments: dict = {}
        archive_paths: list[Path] = []

        def add_json(key: str, path: Path | None) -> None:
            item = json_attachment(path)
            if item is None:
                return
            attachments[key] = item
            archive_paths.append(path)

        middle_path = base_dir / f"{input_path.name}_middle.json"
        lines_path = base_dir / f"{input_path.name}_lines.json"
        if middle_path.exists() and not lines_path.exists():
            from file_conversion_router.services.sentence_mapping_service import (
                generate_lines_json_from_middle_json,
            )
            generate_lines_json_from_middle_json(str(middle_path), str(lines_path))

        add_json("bbox", lines_path)
        add_json("layout", middle_path)
        add_json("content_list", base_dir / f"{input_path.name}_content_list.json")

        pdf_images_dir = base_dir / f"{input_path.name}_images"
        pdf_images = []
        for image_path in iter_image_files(pdf_images_dir) or []:
            pdf_images.append(binary_attachment(image_path, include_binary_attachments))
            archive_paths.append(image_path)
        if pdf_images:
            attachments["pdf_images"] = pdf_images

        return attachments, archive_paths

    def generate_index_helper(self, data, md=None):
        self.index_helper = []
        for item in data:
            if item.get('text_level') == 1:
                title = item['text'].strip()
                if title.startswith('# '):
                    title = title[2:]
                # Strip markdown bold/italic formatting to avoid matching failures
                title = title.replace('*', '').strip()

                skip_patterns = [
                    re.compile(r'^\s*ROAR ACADEMY EXERCISES\s*$', re.I),
                    re.compile(r'^\s*(?:#+\s*)+$')  # lines that are only # + spaces
                ]
                if any(p.match(title) for p in skip_patterns):
                    continue

                if not title:
                    continue

                # Check if title appears after any number of # symbols
                if md:
                    lines = md.split('\n')
                    title_found = False
                    for line in lines:
                        stripped_line = line.strip()
                        if stripped_line.startswith('#'):
                            # Extract and normalize heading text for comparison
                            heading_text = re.sub(r'^#+\s*', '', stripped_line).strip()
                            heading_text_clean = heading_text.replace('*', '').strip()
                            if heading_text_clean == title:
                                title_found = True
                                break

                    if title_found:
                        page_index = item['page_idx'] + 1  # 1-based
                        self.index_helper.append({title: page_index})
