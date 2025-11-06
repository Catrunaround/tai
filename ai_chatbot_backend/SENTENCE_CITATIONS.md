# Sentence-Level Citations with Bounding Box Support

This document describes the sentence-level citation feature that enables precise tracking of which sentences from reference documents were used to answer user questions, including their exact location (bounding box) in the original PDF files.

## Overview

### Problem
Previously, the system could only cite entire chunks (paragraphs) as references. This made it difficult to:
- Identify exactly which sentences contributed to an answer
- Display precise locations in PDF viewers
- Provide granular source attribution

### Solution
The new feature enables:
1. **LLM Self-Citation**: The model identifies which sentences it used while generating answers
2. **Bounding Box Lookup**: Maps those sentences to precise coordinates in PDF files
3. **Enhanced API Response**: Returns sentence-level citations with page and bbox data
4. **Frontend-Ready**: Structured format for highlighting specific sentences in PDF viewers

## Architecture

### Data Flow

```
1. User Question
   ↓
2. RAG Retrieval (chunks from database)
   ↓
3. LLM Generation with Structured Output
   {
     "answer": "The actual answer...",
     "mentioned_contexts": ["sentence 1", "sentence 2", ...]
   }
   ↓
4. Context Matching Service
   - Matches mentioned_contexts to sentence_mapping in database
   - Retrieves bboxes from file.extra_info
   ↓
5. Enhanced Response
   {
     "answer": "...",
     "references": [
       {
         "file_uuid": "...",
         "sentences": [
           {
             "content": "sentence text",
             "page_index": 0,
             "bbox": [x1, y1, x2, y2]
           }
         ]
       }
     ]
   }
```

### Database Schema

#### Sentence Mapping Storage
Sentence mappings are stored in `file.extra_info` as JSON:

```json
{
  "sentence_mapping": [
    {
      "index": 0,
      "page_index": 0,
      "block_type": "text",
      "spans": [
        {
          "bbox": [51, 150, 561, 222],
          "content": "Learning to use if and while is an essential skill.",
          "type": "text"
        }
      ]
    }
  ]
}
```

#### Database Tables
- **file**: Stores `extra_info` JSON blob with sentence_mapping
- **chunks**: Stores chunk text and embeddings (no schema changes needed)

## Components

### 1. Database Models (`app/core/models/metadata.py`)

Added helper methods to `FileModel`:

```python
def get_sentence_mapping(self) -> Optional[List[Dict[str, Any]]]:
    """Parse and return sentence mapping from extra_info JSON"""

def get_extra_info_dict(self) -> Dict[str, Any]:
    """Parse and return the entire extra_info as a dictionary"""
```

### 2. Pydantic Schemas (`app/schemas/citations.py`)

New schemas for structured citation data:

- **SentenceCitation**: Single sentence with bbox and page info
- **EnhancedReference**: Backward-compatible reference with optional sentence list
- **FileSentenceMappingResponse**: Response for sentence mapping API endpoint

### 3. Citation Service (`app/services/sentence_citation_service.py`)

Core service with three main functions:

#### a. Parse Structured Response
```python
SentenceCitationService.parse_structured_response(response_text: str) -> Dict
```
Extracts `answer` and `mentioned_contexts` from LLM JSON response.

#### b. Match Contexts to Sentences
```python
SentenceCitationService.match_contexts_to_sentences(
    mentioned_contexts: List[str],
    chunks: List[Dict]
) -> Dict[str, List[SentenceCitation]]
```
- Matches mentioned contexts to sentence mappings in database
- Uses fuzzy matching (85% similarity threshold) to handle text variations
- Returns dict mapping file_uuid → list of SentenceCitation objects

#### c. Build Citation Prompt
```python
SentenceCitationService.build_citation_prompt_addition() -> str
```
Returns prompt text instructing the LLM to use structured output format.

### 4. RAG Retriever Extensions (`app/services/rag_retriever.py`)

Added helper functions:

```python
def get_sentence_mapping_by_file_uuid(file_uuid: str) -> Optional[List[Dict]]
def get_file_info_by_uuid(file_uuid: str) -> Optional[Dict]
```

### 5. RAG Generation Integration (`app/services/rag_generation.py`)

#### a. Modified System Prompt
`format_chat_msg()` now accepts `enable_citations=True` parameter and adds citation instructions to system message.

#### b. Response Enhancement
```python
def enhance_references_with_sentence_citations(
    response_text: str,
    reference_list: List[List],
    chunks_data: List[Dict]
) -> Tuple[str, List[Dict]]
```
Post-processes LLM response to extract sentence citations and enhance reference list.

### 6. API Endpoint (`app/api/routes/files.py`)

New endpoint for on-demand sentence mapping retrieval:

```
GET /api/files/{file_id}/sentence_mapping
```

**Response:**
```json
{
  "file_uuid": "660e8400-e29b-41d4-a716-446655440001",
  "file_name": "disc01.pdf",
  "file_path": "CS61A/discussions/disc01.pdf",
  "has_sentence_mapping": true,
  "total_blocks": 50,
  "total_pages": 4,
  "sentence_mapping": [...]
}
```

## Usage

### For Backend Developers

#### 1. Enable Citations in Chat Generation

```python
from app.services.rag_generation import generate_chat_response

# Enable sentence citations
response, references = await generate_chat_response(
    messages=messages,
    course="CS61A",
    engine=engine,
    enable_sentence_citations=True  # Enable feature
)
```

#### 2. Enhance References (Post-Processing)

```python
from app.services.rag_generation import enhance_references_with_sentence_citations

# After getting full response (non-streaming)
answer, enhanced_refs = enhance_references_with_sentence_citations(
    response_text=full_response,
    reference_list=original_references,
    chunks_data=retrieved_chunks
)
```

#### 3. Retrieve Sentence Mapping via API

```bash
curl -X GET "http://localhost:8000/api/files/{file_uuid}/sentence_mapping" \
     -H "Authorization: Bearer YOUR_TOKEN"
```

### For Frontend Developers

#### Expected Response Format

When citations are enabled, references include sentence-level data:

```javascript
{
  "answer": "The race function simulates a race between...",
  "references": [
    {
      "topic_path": "CS61A > Discussion 01 > Q1: Race",
      "url": "https://cs61a.org/disc/disc01.pdf",
      "file_path": "CS61A/discussions/disc01.pdf",
      "file_uuid": "660e8400-e29b-41d4-a716-446655440001",
      "chunk_index": 6,
      "sentences": [
        {
          "content": "The race function below sometimes returns the wrong value...",
          "page_index": 0,
          "bbox": [52, 255, 444, 269],
          "block_type": "text"
        }
      ]
    }
  ]
}
```

#### Displaying Citations in PDF Viewer

```javascript
// Example using PDF.js
function highlightCitation(pdfViewer, citation) {
  const { page_index, bbox } = citation;
  const [x1, y1, x2, y2] = bbox;

  // Navigate to page
  pdfViewer.currentPageNumber = page_index + 1;

  // Draw highlight rectangle
  pdfViewer.addHighlight({
    page: page_index,
    rect: { x1, y1, x2, y2 },
    color: 'rgba(255, 255, 0, 0.3)'
  });
}
```

## Configuration

### Enable/Disable Citations

Set via function parameter:
```python
enable_sentence_citations=True  # Enable (default)
enable_sentence_citations=False # Disable (backward compatible)
```

### Fuzzy Matching Threshold

Adjust in `sentence_citation_service.py`:
```python
# Line ~105
if similarity > best_score and similarity >= 0.85:  # Adjust threshold here
```

Lower threshold = more matches but less precision
Higher threshold = fewer matches but higher precision

## Testing

### Run Test Suite

```bash
cd /Users/yyk956614/tai/ai_chatbot_backend
python tests/test_sentence_citations.py
```

### Manual Testing

1. **Test Structured Response Parsing:**
   ```python
   from app.services.sentence_citation_service import SentenceCitationService

   response = '{"answer": "...", "mentioned_contexts": [...]}'
   parsed = SentenceCitationService.parse_structured_response(response)
   ```

2. **Test Sentence Mapping Retrieval:**
   ```bash
   curl "http://localhost:8000/api/files/{file_uuid}/sentence_mapping"
   ```

3. **Test with disc01.pdf:**
   - File should have sentence_mapping in database
   - Ask question: "What is the race function?"
   - Check if response includes sentence citations

## Limitations & Future Work

### Current Limitations

1. **PDF Only**: Bounding boxes only available for PDF files processed with MinerU
2. **Non-Streaming**: Full citation enhancement requires collecting complete response
3. **Fuzzy Matching**: May miss or incorrectly match sentences with significant text variations
4. **No Cross-File Aggregation**: Citations are per-file, not deduplicated across files

### Future Enhancements

1. **Streaming Support**: Implement streaming parser for incremental citation extraction
2. **Multi-Format Support**: Extend to HTML, markdown, and other file types
3. **Improved Matching**: Use semantic similarity instead of string matching
4. **Citation Analytics**: Track which sentences are most frequently cited
5. **User Feedback Loop**: Allow users to correct citation matches

## Troubleshooting

### Issue: No sentence mappings returned

**Cause**: File's `extra_info` doesn't contain `sentence_mapping`

**Solution**:
1. Check if file was processed with MinerU
2. Run sentence mapping generation:
   ```bash
   cd /Users/yyk956614/tai/rag
   python file_conversion_router/scripts/add_sentence_mapping.py \
       --lines-json path/to/file.pdf_lines.json \
       --db metadata.db \
       --file-name file.pdf \
       --course CS61A
   ```

### Issue: LLM not returning structured output

**Cause**: Model not following JSON format instructions

**Solution**:
1. Check if `enable_sentence_citations=True` is set
2. Verify system prompt includes citation instructions
3. Try lower temperature for more deterministic output
4. Consider using a model better at following JSON schemas

### Issue: Sentences not matching

**Cause**: Text differences between chunk and sentence mapping

**Solution**:
1. Lower fuzzy matching threshold (line 105 in service)
2. Check text normalization logic
3. Verify sentence mapping data quality

## Files Modified/Created

### Created
- `app/schemas/citations.py` - Citation Pydantic schemas
- `app/services/sentence_citation_service.py` - Core citation service
- `tests/test_sentence_citations.py` - Test suite
- `SENTENCE_CITATIONS.md` - This documentation

### Modified
- `app/core/models/metadata.py` - Added sentence mapping helpers
- `app/services/rag_retriever.py` - Added sentence mapping retrieval functions
- `app/services/rag_generation.py` - Integrated citation tracking
- `app/api/routes/files.py` - Added sentence mapping endpoint

## Related Documentation

- [RAG Backend Documentation](.claude/memory/claude-backend.md)
- [RAG Pipeline Documentation](.claude/memory/claude-rag.md)
- [Main Project README](CLAUDE.md)

## Questions?

For issues or questions:
1. Check this documentation
2. Review test cases in `tests/test_sentence_citations.py`
3. Examine example data in `rag/file_conversion_router/tests/disc01/`
