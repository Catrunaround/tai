"""
Clean, simple file schemas - no over-engineering
"""

from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field


class FileMetadata(BaseModel):
    """Simple, clean file metadata"""

    # API fields
    uuid: str = Field(..., description="Unique file identifier")
    filename: str = Field(..., description="Original filename")
    title: Optional[str] = Field(None, description="Clean, formatted title")
    relative_path: str = Field(..., description="Path relative to data directory")

    # File properties
    size_bytes: int = Field(..., description="File size in bytes")
    mime_type: str = Field(..., description="MIME type")
    created_at: Optional[datetime] = Field(None, description="File creation timestamp")
    modified_at: Optional[datetime] = Field(
        None, description="Last modification timestamp"
    )

    # Simple metadata
    course: Optional[str] = Field(None, description="Course code (e.g., CS61A)")
    category: Optional[str] = Field(
        None, description="File category (document, video, audio, other)"
    )

    @classmethod
    def from_db_model(cls, db_model):
        """Create schema from database model with proper field mapping"""
        return cls(
            uuid=str(db_model.id),
            filename=db_model.file_name,
            title=db_model.title,
            relative_path=db_model.relative_path,
            size_bytes=db_model.size_bytes,
            mime_type=db_model.mime_type,
            created_at=db_model.created_at,
            modified_at=db_model.modified_at,
            course=db_model.course_code,
            category=db_model.category,
        )

    class Config:
        json_schema_extra = {
            "example": {
                "uuid": "550e8400-e29b-41d4-a716-446655440000",
                "filename": "lab_01_getting_started.pdf",
                "title": "Lab 01 Getting Started",
                "relative_path": "CS61A/documents/lab_01_getting_started.pdf",
                "size_bytes": 1048576,
                "mime_type": "application/pdf",
                "created_at": "2023-01-01T00:00:00Z",
                "modified_at": "2023-01-01T00:00:00Z",
                "course": "CS61A",
                "category": "document",
            }
        }


class FileListResponse(BaseModel):
    """Response for file listing"""

    files: List[FileMetadata] = Field(..., description="List of files")
    total_count: int = Field(..., description="Total number of files")
    page: int = Field(..., description="Current page number")
    limit: int = Field(..., description="Items per page")
    has_next: bool = Field(..., description="Whether there are more pages")
    has_prev: bool = Field(..., description="Whether there are previous pages")

    # Applied filters for transparency
    filters_applied: dict = Field(
        default_factory=dict, description="Filters that were applied"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "files": [
                    {
                        "uuid": "550e8400-e29b-41d4-a716-446655440000",
                        "filename": "lab_01.pdf",
                        "title": "Lab 01",
                        "relative_path": "CS61A/documents/lab_01.pdf",
                        "size_bytes": 1048576,
                        "mime_type": "application/pdf",
                        "created_at": "2023-01-01T00:00:00Z",
                        "modified_at": "2023-01-01T00:00:00Z",
                        "course": "CS61A",
                        "category": "document",
                    }
                ],
                "total_count": 1,
                "page": 1,
                "limit": 100,
                "has_next": False,
                "has_prev": False,
                "filters_applied": {"course": "CS61A", "category": "document"},
            }
        }


class FileStatsResponse(BaseModel):
    """Simple file statistics"""

    total_files: int = Field(..., description="Total number of files")
    base_directory: str = Field(..., description="Base directory path")
    auto_discovery: str = Field(..., description="Auto-discovery status")
    courses: dict = Field(..., description="Course breakdown with counts")
    last_updated: datetime = Field(..., description="Last update timestamp")

    class Config:
        json_schema_extra = {
            "example": {
                "total_files": 150,
                "base_directory": "/path/to/data",
                "auto_discovery": "enabled",
                "courses": {"CS61A": 75, "CS61B": 50, "CS70": 25},
                "last_updated": "2023-01-01T12:00:00Z",
            }
        }


class ErrorResponse(BaseModel):
    """Standard error response"""

    detail: str = Field(..., description="Error message")
    error_code: Optional[str] = Field(None, description="Error code")

    class Config:
        json_schema_extra = {
            "example": {"detail": "File not found", "error_code": "FILE_NOT_FOUND"}
        }


# Simple query parameters
class FileListParams(BaseModel):
    """Simple query parameters for file listing"""

    course: Optional[str] = Field(None, description="Filter by course")
    category: Optional[str] = Field(None, description="Filter by category")
    search: Optional[str] = Field(None, description="Search in filename and title")
    page: int = Field(1, ge=1, description="Page number")
    limit: int = Field(100, ge=1, le=1000, description="Items per page")

    class Config:
        json_schema_extra = {
            "example": {
                "course": "CS61A",
                "category": "document",
                "search": "lab",
                "page": 1,
                "limit": 50,
            }
        }
