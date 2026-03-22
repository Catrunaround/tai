"""
Unit tests for the page SSE protocol changes:
  1. New event models (PageOpen, PageClose, BlockOpen, BlockClose)
  2. Citation marker parsing (_parse_speech_citations)
  3. Fallback when LLM produces no markers
  4. Full SSE serialization round-trip

Run:  cd ai_chatbot_backend && python -m pytest tests/test_page_sse_protocol.py -v
"""
import json
import pytest

from app.core.models.chat_completion import (
    BlockClose,
    BlockOpen,
    CitationClose,
    CitationOpen,
    PageClose,
    PageDelta,
    PageOpen,
    PageSpeech,
    SpeechCitation,
    sse,
)
from app.services.generation.tutor.generate_pages import _parse_speech_citations


# ---------------------------------------------------------------------------
# 1. Model serialization
# ---------------------------------------------------------------------------

class TestEventModels:
    def test_page_open_serialization(self):
        evt = PageOpen(page_index=1, point="Binary Search", goal="Understand divide-and-conquer")
        data = json.loads(evt.model_dump_json())
        assert data["type"] == "page.open"
        assert data["page_index"] == 1
        assert data["point"] == "Binary Search"
        assert data["goal"] == "Understand divide-and-conquer"

    def test_page_close_serialization(self):
        evt = PageClose(page_index=2)
        data = json.loads(evt.model_dump_json())
        assert data["type"] == "page.close"
        assert data["page_index"] == 2

    def test_block_open_serialization(self):
        evt = BlockOpen(page_index=1, block_type="readable")
        data = json.loads(evt.model_dump_json())
        assert data["type"] == "block.open"
        assert data["block_type"] == "readable"

    def test_block_open_not_readable(self):
        evt = BlockOpen(page_index=1, block_type="not_readable")
        assert evt.block_type == "not_readable"

    def test_block_open_rejects_invalid_type(self):
        with pytest.raises(Exception):
            BlockOpen(page_index=1, block_type="something_else")

    def test_block_close_serialization(self):
        evt = BlockClose(page_index=1)
        data = json.loads(evt.model_dump_json())
        assert data["type"] == "block.close"

    def test_page_delta_text_only(self):
        evt = PageDelta(page_index=1, seq=0, text="Hello world")
        data = json.loads(evt.model_dump_json())
        assert data["type"] == "page.delta"
        assert data["text"] == "Hello world"
        assert "block_type" not in data  # no longer on PageDelta

    def test_page_delta_rejects_empty_text(self):
        with pytest.raises(Exception):
            PageDelta(page_index=1, seq=0, text="")

    def test_citation_open_with_page_fields(self):
        evt = CitationOpen(
            citation_id=1, quote_text="some quote",
            page_index=2, reference_idx=3, file_path="/a/b.pdf",
        )
        data = json.loads(evt.model_dump_json())
        assert data["type"] == "response.citation.open"
        assert data["page_index"] == 2
        assert data["reference_idx"] == 3
        assert data["file_path"] == "/a/b.pdf"

    def test_citation_open_chat_mode_no_page_fields(self):
        """Chat mode: page_index etc. should be None."""
        evt = CitationOpen(citation_id=1)
        data = json.loads(evt.model_dump_json())
        assert data["page_index"] is None
        assert data["reference_idx"] is None

    def test_citation_close_with_page_fields(self):
        evt = CitationClose(citation_id=1, page_index=2, reference_idx=3)
        data = json.loads(evt.model_dump_json())
        assert data["page_index"] == 2
        assert data["reference_idx"] == 3


# ---------------------------------------------------------------------------
# 2. SSE formatting
# ---------------------------------------------------------------------------

class TestSSE:
    def test_sse_format(self):
        evt = PageOpen(page_index=1, point="Test", goal="goal")
        result = sse(evt)
        assert result.startswith("data: ")
        assert result.endswith("\n\n")
        payload = json.loads(result[len("data: "):].strip())
        assert payload["type"] == "page.open"

    def test_sse_event_ordering(self):
        """Simulate a minimal page lifecycle and verify event types."""
        events = [
            PageOpen(page_index=1, point="Intro", goal="Learn"),
            BlockOpen(page_index=1, block_type="readable"),
            CitationOpen(citation_id=1, page_index=1, reference_idx=2),
            PageDelta(page_index=1, seq=0, text="Some content"),
            CitationClose(citation_id=1, page_index=1, reference_idx=2),
            BlockClose(page_index=1),
            PageClose(page_index=1),
        ]
        types = []
        for evt in events:
            line = sse(evt)
            payload = json.loads(line[len("data: "):].strip())
            types.append(payload["type"])

        assert types == [
            "page.open",
            "block.open",
            "response.citation.open",
            "page.delta",
            "response.citation.close",
            "block.close",
            "page.close",
        ]


# ---------------------------------------------------------------------------
# 3. _parse_speech_citations
# ---------------------------------------------------------------------------

class TestParseSpeechCitations:
    """Test the [cite:N] / [/cite:N] marker parser."""

    def _make_page_citations(self):
        """Build sample page_citations metadata (from content streaming phase)."""
        return [
            SpeechCitation(
                action="open", citation_id=1, char_offset=0,
                quote_text="binary search definition",
                reference_idx=3, file_path="/docs/algo.pdf",
            ),
            SpeechCitation(
                action="close", citation_id=1, char_offset=0,
                reference_idx=3,
            ),
            SpeechCitation(
                action="open", citation_id=2, char_offset=0,
                quote_text="time complexity",
                reference_idx=5, file_path="/docs/complexity.pdf",
            ),
            SpeechCitation(
                action="close", citation_id=2, char_offset=0,
                reference_idx=5,
            ),
        ]

    def test_basic_marker_parsing(self):
        raw = "Now [cite:1]binary search works by dividing the interval.[/cite:1] Pretty neat!"
        page_cites = self._make_page_citations()

        clean, cites = _parse_speech_citations(raw, page_cites)

        # Markers stripped
        assert "[cite" not in clean
        assert clean == "Now binary search works by dividing the interval. Pretty neat!"

        # Two citation events: open and close
        assert len(cites) == 2
        assert cites[0].action == "open"
        assert cites[0].citation_id == 1
        assert cites[0].char_offset == 4  # "Now " = 4 chars
        assert cites[0].reference_idx == 3
        assert cites[0].file_path == "/docs/algo.pdf"
        assert cites[0].quote_text == "binary search definition"

        assert cites[1].action == "close"
        assert cites[1].citation_id == 1
        assert cites[1].char_offset == 49  # "Now " (4) + "binary search works by dividing the interval." (45)

    def test_multiple_citations(self):
        raw = "[cite:1]First ref.[/cite:1] Then [cite:2]second ref.[/cite:2]"
        page_cites = self._make_page_citations()

        clean, cites = _parse_speech_citations(raw, page_cites)

        assert clean == "First ref. Then second ref."
        assert len(cites) == 4  # open1, close1, open2, close2

        # Verify ordering and offsets
        assert cites[0].action == "open"
        assert cites[0].citation_id == 1
        assert cites[0].char_offset == 0

        assert cites[1].action == "close"
        assert cites[1].citation_id == 1
        assert cites[1].char_offset == 10  # "First ref."

        assert cites[2].action == "open"
        assert cites[2].citation_id == 2
        assert cites[2].char_offset == 16  # "First ref. Then "

        assert cites[3].action == "close"
        assert cites[3].citation_id == 2
        assert cites[3].char_offset == 27  # "First ref. Then second ref."

    def test_no_markers_fallback(self):
        """When LLM produces no markers, fall back to original page_citations."""
        raw = "Just a plain speech with no markers at all."
        page_cites = self._make_page_citations()

        clean, cites = _parse_speech_citations(raw, page_cites)

        assert clean == raw  # unchanged
        assert cites is page_cites  # exact same list returned

    def test_no_markers_no_page_citations(self):
        """No markers and no page_citations → empty list."""
        raw = "Just a plain speech."
        clean, cites = _parse_speech_citations(raw, [])

        assert clean == raw
        assert cites == []

    def test_unknown_citation_id(self):
        """Marker references a citation_id not in page_citations → still parsed, metadata is None."""
        raw = "See [cite:99]this part.[/cite:99]"
        page_cites = self._make_page_citations()  # only has ids 1 and 2

        clean, cites = _parse_speech_citations(raw, page_cites)

        assert clean == "See this part."
        assert len(cites) == 2
        assert cites[0].citation_id == 99
        assert cites[0].reference_idx is None
        assert cites[0].file_path is None


# ---------------------------------------------------------------------------
# 4. SpeechCitation in PageSpeech
# ---------------------------------------------------------------------------

class TestPageSpeechWithOffset:
    def test_speech_citation_serialization(self):
        speech = PageSpeech(
            page_index=1,
            speech_text="Now binary search works by dividing the interval.",
            citations=[
                SpeechCitation(
                    action="open", citation_id=1, char_offset=4,
                    quote_text="binary search", reference_idx=3,
                    file_path="/docs/algo.pdf",
                ),
                SpeechCitation(
                    action="close", citation_id=1, char_offset=50,
                    reference_idx=3,
                ),
            ],
        )
        data = json.loads(speech.model_dump_json())

        assert data["type"] == "page.speech"
        assert len(data["citations"]) == 2
        assert data["citations"][0]["char_offset"] == 4
        assert data["citations"][0]["file_path"] == "/docs/algo.pdf"
        assert data["citations"][1]["char_offset"] == 50

    def test_speech_with_empty_citations(self):
        speech = PageSpeech(page_index=0, speech_text="Intro speech.", citations=[])
        data = json.loads(speech.model_dump_json())
        assert data["citations"] == []
