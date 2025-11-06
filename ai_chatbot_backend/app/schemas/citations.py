"""
Schemas for sentence-level citations with bounding box support
"""

from typing import List, Optional
from pydantic import BaseModel, Field


class SentenceCitation(BaseModel):
    """A single sentence citation with bounding box location(s)"""
    content: str = Field(..., description="Sentence text content")
    page_index: int = Field(..., description="Page number (0-indexed)")
    bbox: List[float] = Field(..., description="Primary bounding box coordinates [x1, y1, x2, y2] (first region)")
    block_type: Optional[str] = Field(None, description="Type of block (text, title, etc.)")
    bboxes: Optional[List[List[float]]] = Field(
        None,
        description="All bounding boxes if citation spans multiple lines/regions [[x1,y1,x2,y2], ...]"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "content": "Learning to use if and while is an essential skill.",
                "page_index": 0,
                "bbox": [51, 150, 561, 222],
                "block_type": "text",
                "bboxes": [[51, 150, 561, 172], [51, 172, 561, 222]]
            }
        }


class EnhancedReference(BaseModel):
    """Enhanced reference with sentence-level citations (backward compatible)"""
    # Original reference_list fields
    topic_path: str = Field(..., description="Hierarchical topic path")
    url: Optional[str] = Field(None, description="URL to source")
    file_path: str = Field(..., description="File path")
    file_uuid: str = Field(..., description="File UUID")
    chunk_index: int = Field(..., description="Chunk index")

    # New sentence-level citations (optional for backward compatibility)
    sentences: Optional[List[SentenceCitation]] = Field(
        None,
        description="Specific sentences used from this chunk with bboxes"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "topic_path": "CS61A > Discussion 01 > While and If",
                "url": "https://cs61a.org/disc/disc01.pdf",
                "file_path": "CS61A/discussions/disc01.pdf",
                "file_uuid": "660e8400-e29b-41d4-a716-446655440001",
                "chunk_index": 5,
                "sentences": [
                    {
                        "content": "Learning to use if and while is an essential skill.",
                        "page_index": 0,
                        "bbox": [51, 150, 561, 222],
                        "block_type": "text"
                    }
                ]
            }
        }


class FileSentenceMappingResponse(BaseModel):
    """Response for the sentence mapping endpoint"""
    file_uuid: str = Field(..., description="File UUID")
    file_name: str = Field(..., description="Original filename")
    has_sentence_mapping: bool = Field(..., description="Whether sentence mapping exists")
    sentence_mapping: Optional[List[dict]] = Field(
        None,
        description="Raw sentence mapping data from extra_info"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "file_uuid": "660e8400-e29b-41d4-a716-446655440001",
                "file_name": "disc01.pdf",
                "has_sentence_mapping": True,
                "sentence_mapping": [
                    {
                        "index": 0,
                        "page_index": 0,
                        "block_type": "title",
                        "spans": [
                            {
                                "bbox": [51, 116, 154, 146],
                                "content": "While and If",
                                "type": "text"
                            }
                        ]
                    }
                ]
            }
        }
