from pathlib import Path
import re
import nbformat
from nbconvert import MarkdownExporter
import yaml
from file_conversion_router.classes.page import Page
from file_conversion_router.conversion.base_converter import BaseConverter


class NotebookConverter(BaseConverter):
    def __init__(self, course_name, course_id):
        super().__init__(course_name, course_id)
        self.index_helper = [{}]

    def extract_all_markdown_titles(self, content):
        """
        Extract ALL possible titles from markdown content
        Returns a list of all found titles
        """
        if not content.strip():
            return []

        titles = []
        header_matches = re.findall(r'^(#{1,6})\s+(.+)$', content, re.MULTILINE)
        for level, title in header_matches:
            clean_title = title.strip()
            if clean_title:
                titles.append(clean_title)

        bold_matches = re.findall(r'\*\*([^*]+)\*\*', content)
        for bold_text in bold_matches:
            clean_bold = bold_text.strip()
            # If bold text is short enough to be a title and not already found
            if (len(clean_bold) <= 100 and
                    '\n' not in clean_bold and
                    clean_bold not in titles):
                titles.append(clean_bold)
        if not titles:
            first_line = content.split('\n')[0].strip()
            if (len(first_line) <= 80 and
                    not first_line.startswith('```') and
                    not first_line.startswith('    ') and
                    not re.search(r'[{}()\[\]<>]', first_line)):
                titles.append(first_line)
        if not titles:
            # Keep formatting but normalize whitespace
            clean_content = re.sub(r'\n+', ' ', content).strip()

            words = clean_content.split()
            if words:
                first_20_words = ' '.join(words[:20])
                titles.append(first_20_words)

        return titles

    def generate_index_helper(self, notebook_content):
        """
        Create index helper from notebook content
        Now supports multiple titles per cell

        Args:
            notebook_content: nbformat notebook object

        Returns:
            list: List of dictionaries with cell titles/names as keys and indices as values
        """
        self.index_helper = []
        code_counter = 1
        for i, cell in enumerate(notebook_content.cells):
            if cell.cell_type == 'markdown':
                titles = self.extract_all_markdown_titles(cell.source)
                self.index_helper.append({title: i + 1 for title in titles})
            elif cell.cell_type == 'code':
                if cell.source.strip():
                    self.index_helper.append({f"Code Cell {code_counter}": i + 1})
                    code_counter += 1
    # Override
    def _to_markdown(self, input_path: Path, output_path: Path) -> Path:
        output_path = output_path.with_suffix(".md")

        with open(input_path, "r") as input_file, open(output_path, "w") as output_file:
            content = nbformat.read(input_file, as_version=4)
            self.generate_index_helper(content)
            markdown_converter = MarkdownExporter()
            (markdown_content, resources) = markdown_converter.from_notebook_node(
                content
            )
            output_file.write(self._post_process_markdown(markdown_content))
        return output_path

    def _post_process_markdown(self, markdown_content: str) -> str:
        lines = markdown_content.split("\n")[
            1:
        ]  # first line is the title of the course section

        processed_lines = []
        for i, line in enumerate(lines):
            if i == 1:  # convert lecture title to h1
                processed_lines.append(f"# {line.lstrip('#').strip()}")
            elif line.startswith("#"):  # convert all other heading down one level
                processed_lines.append(f"#{line.strip()}")
            else:
                processed_lines.append(line.strip())
        return "\n".join(processed_lines)
