import os
import re
from pathlib import Path
import json

from file_conversion_router.conversion.base_converter import BaseConverter

from file_conversion_router.services.tai_MinerU_service.api import (
    convert_pdf_to_md_by_MinerU,
)


class PdfConverter(BaseConverter):
    def __init__(self, course_name, course_id):
        super().__init__(course_name, course_id)
        self.available_tools = ["nougat", "MinerU"]

    def is_tool_supported(self, tool_name):
        """
        Check if a tool is supported.
        """
        return tool_name in self.available_tools

    def remove_image_links(self, text):
        """
        Remove image links from the text.
        """
        # Regular expression to match image links
        image_link_pattern = r"!\[.*?\]\(.*?\)"
        # Remove all image links
        return re.sub(image_link_pattern, "", text)

    def clean_markdown_content(self, markdown_path):
        with open(markdown_path, "r", encoding="utf-8") as file:
            content = file.read()
        cleaned_content = self.remove_image_links(content)
        with open(markdown_path, "w", encoding="utf-8") as file:
            file.write(cleaned_content)

    def validate_tool(self, tool_name):
        """
        Validate if the tool is supported, raise an error if not.
        """
        if not self.is_tool_supported(tool_name):
            raise ValueError(
                f"Tool '{tool_name}' is not supported. Available tools: {', '.join(self.available_tools)}"
            )

    # Override
    def _to_markdown(
        self, input_path: Path, output_path: Path, conversion_method: str = "MinerU"
    ) -> Path:
        self.validate_tool(conversion_method)
        temp_dir_path = output_path.parent

        # Create the directory if it doesn't exist
        if not temp_dir_path.exists():
            os.makedirs(temp_dir_path)
        if conversion_method == "MinerU":
            new_output_path = output_path.with_suffix("")
            convert_pdf_to_md_by_MinerU(input_path, new_output_path)
            base_name = input_path.stem  # e.g., "07-Function_Examples_1pp"
            md_file_path = new_output_path.parent / f"{base_name}.md"
            if md_file_path.exists():
                print(f"Markdown file found: {md_file_path}")
            else:
                raise FileNotFoundError(f"Markdown file not found: {md_file_path}")
            # Set the target to this markdown path
            target = md_file_path
            self.clean_markdown_content(target)
        return target

    def title_to_index(self, md_path: Path) -> dict[str, int]:
        """
        Map every Markdown heading in ``md_path`` to its page index,
        as recorded in the companion ``*_content_list.json`` file.

        Returns
        -------
        dict
            {title_text: page_idx}
        """
        json_path = md_path.with_name(f"{md_path.stem}_content_list.json")
        with open(json_path, encoding="utf-8") as jf:
            json_content = json.load(jf)
        text_to_page_idx = {
            item["text"].strip(): item["page_idx"] + 1 for item in json_content
        }
        heading_re = re.compile(r"^\s*#+\s*(.+?)\s*$")  # any level of '#'
        title_to_idx: dict[str, int] = {}
        with md_path.open(encoding="utf-8") as mf:
            for lineno, line in enumerate(mf, 1):
                m = heading_re.match(line)
                if not m:
                    continue
                title = m.group(1).strip()
                try:
                    title_to_idx[title] = text_to_page_idx[title]
                except KeyError:
                    raise KeyError(
                        f"Heading on line {lineno} not found in JSON: {title!r}"
                    ) from None

        if not title_to_idx:
            raise ValueError("No markdown headings found in the file.")
        return title_to_idx


