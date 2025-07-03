from abc import ABC, abstractmethod
from pathlib import Path
from typing import Union
import json

from nltk.app.wordnet_app import explanation
from openai import OpenAI
from openai.types.chat import ChatCompletionMessage


class MarkdownStructureBase(ABC):
    # TODO change name to post processing helper
    # TODO move to conversion classes
    """
    Abstract base class for structuring markdown content from different sources.
    It defines a common workflow and handles shared functionalities like
    initializing the OpenAI client and saving responses.
    """

    def __init__(self, api_key: str, file_path: Union[str, Path], course_name: str):
        self.client = OpenAI(api_key=api_key)
        self.file_path = Path(file_path)
        self.course_name = course_name

        if not self.file_path.exists():
            raise FileNotFoundError(f"The file {self.file_path} does not exist.")

    def apply_markdown_structure(self) -> Path:
        # TODO change from file type to title levels and file type
        print(f"--- Starting processing for {self.file_path.name} ---")
        print("Getting structured content from OpenAI...")
        content_dict = self._get_structured_content()
        output_file_path = self.file_path.parent / f"{self.file_path.stem}_structured.md"
        print(f"Applying structure and writing to {output_file_path}...")
        self._apply_structure_to_markdown(content_dict, output_file_path)
        metadata_path = self.file_path.with_name(f"{self.file_path.stem}_metadata.yaml")
        self.save_key_concept_to_metadata(content_dict, metadata_path)
        print(f"--- Successfully finished processing for {self.file_path.name} ---")

        return output_file_path


    @abstractmethod
    def _get_structured_content(self) -> ChatCompletionMessage:
        pass

    @abstractmethod
    def _apply_structure_to_markdown(self, content_dict, output_path: Path):
        pass

    def save_key_concept_to_metadata(self, json_dict, metadata_path: Path):
        key_concept = json_dict["key_concepts"]
        with open(metadata_path, "w") as f:
            json.dump(key_concept, f)
        return key_concept