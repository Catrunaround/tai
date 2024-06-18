from pathlib import Path
import yaml
from rag.file_conversion_router.conversion.base_converter import BaseConverter
from rag.file_conversion_router.classes.page import Page
from rag.file_conversion_router.classes.chunk import Chunk

class MarkdownConverter(BaseConverter):
    def __init__(self):
        super().__init__()

    # Override

    def _to_page(self, input_path: Path, output_path: Path, url) -> Page:
        """Perform Markdown to Page conversion."""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        # parent = input_path.parent
        stem = input_path.stem
        filetype = input_path.suffix.split(".")[1]
        with open(input_path, "r") as input_file:
            text = input_file.read()
        metadata = output_path / (stem+"_metadata.yaml")
        with open(metadata, "r") as metadata_file:
            metadata_content = yaml.safe_load(metadata_file)
        url = metadata_content["URL"]
        return Page(content={'text': text}, filetype=filetype, page_url=url)

    def _to_chunk(self, page: Page) -> list[Chunk]:
        """Perform Page to Chunk conversion."""
        page.page_seperate_to_segments()
        page.tree_print()
        return page.tree_segments_to_chunks()
