"""Session-scoped in-memory cache for student-uploaded file chunks.

Uploaded chunks are stored purely in memory, keyed by session ID (sid).
They are searched alongside the course DB during RAG queries and evicted
after a configurable TTL.
"""

import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np


@dataclass
class SessionUploadIndex:
    """Aggregated index for all uploaded files in a session."""

    M: Optional[np.ndarray] = None  # [total_chunks, D] embedding matrix

    chunk_texts: List[str] = field(default_factory=list)
    chunk_uuids: List[str] = field(default_factory=list)
    chunk_titles: List[str] = field(default_factory=list)
    file_paths: List[str] = field(default_factory=list)
    reference_paths: List[str] = field(default_factory=list)
    file_uuids: List[str] = field(default_factory=list)
    file_names: List[str] = field(default_factory=list)
    chunk_idxs: List[int] = field(default_factory=list)
    urls: List[str] = field(default_factory=list)

    last_accessed: float = field(default_factory=time.time)
    created_at: float = field(default_factory=time.time)


# Global cache
_session_cache: Dict[str, SessionUploadIndex] = {}
_session_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def add_upload(
    sid: str,
    file_name: str,
    file_uuid: str,
    chunks: List[dict],
    embeddings: np.ndarray,
) -> int:
    """Append uploaded file chunks + embeddings to a session's index.

    Args:
        sid: Session ID from frontend.
        file_name: Original uploaded file name.
        file_uuid: Deterministic UUID for the file.
        chunks: List of chunk dicts with keys: content, titles, chunk_uuid,
                reference_path, file_path, chunk_index.
        embeddings: numpy array of shape [N, D], float32.

    Returns:
        Total number of chunks in the session after this upload.
    """
    with _session_lock:
        idx = _session_cache.get(sid)
        if idx is None:
            idx = SessionUploadIndex()
            _session_cache[sid] = idx

        for i, chunk in enumerate(chunks):
            idx.chunk_texts.append(chunk.get("content", ""))
            idx.chunk_uuids.append(chunk.get("chunk_uuid", ""))
            idx.chunk_titles.append(chunk.get("titles", ""))
            idx.file_paths.append(chunk.get("file_path", file_name))
            idx.reference_paths.append(chunk.get("reference_path", ""))
            idx.file_uuids.append(file_uuid)
            idx.file_names.append(file_name)
            idx.chunk_idxs.append(chunk.get("chunk_index", i))
            idx.urls.append("")

        # Rebuild stacked embedding matrix
        if idx.M is None:
            idx.M = embeddings.astype(np.float32, copy=False)
        else:
            idx.M = np.vstack([idx.M, embeddings.astype(np.float32, copy=False)])

        idx.last_accessed = time.time()
        return len(idx.chunk_texts)


def search_uploads(
    sid: str,
    query_vec: np.ndarray,
    top_k: int = 5,
    threshold: float = 0.32,
) -> Tuple[
    List[str], List[str], List[str], List[float],
    List[str], List[str], List[str], List[str], List[int],
]:
    """Search uploaded chunks for a session.

    Returns the same 9-tuple format as ``_get_references_from_sql`` in
    ``vector_search.py`` so results can be trivially merged.

    Returns empty lists if no uploads exist for the session.
    """
    empty = ([], [], [], [], [], [], [], [], [])

    with _session_lock:
        idx = _session_cache.get(sid)
    if idx is None or idx.M is None or idx.M.shape[0] == 0:
        return empty

    # Update last_accessed (best-effort, no lock needed for a float write)
    idx.last_accessed = time.time()

    qv = np.asarray(query_vec, dtype=np.float32).ravel()
    scores = idx.M @ qv

    k = min(top_k, idx.M.shape[0])
    top_idx = np.argpartition(scores, -k)[-k:]
    top_idx = top_idx[np.argsort(scores[top_idx])[::-1]]

    # Filter by threshold
    r_uuids, r_texts, r_urls, r_scores = [], [], [], []
    r_file_paths, r_refs, r_titles, r_file_uuids, r_chunk_idxs = [], [], [], [], []

    for i in top_idx:
        s = float(scores[i])
        if s <= threshold:
            continue
        r_uuids.append(idx.chunk_uuids[i])
        r_texts.append(idx.chunk_texts[i])
        r_urls.append(idx.urls[i])
        r_scores.append(s)
        r_file_paths.append(idx.file_paths[i])
        r_refs.append(idx.reference_paths[i])
        r_titles.append(idx.chunk_titles[i])
        r_file_uuids.append(idx.file_uuids[i])
        r_chunk_idxs.append(idx.chunk_idxs[i])

    return (
        r_uuids, r_texts, r_urls, r_scores,
        r_file_paths, r_refs, r_titles, r_file_uuids, r_chunk_idxs,
    )


def get_session(sid: str) -> Optional[SessionUploadIndex]:
    """Return the session index or None."""
    with _session_lock:
        return _session_cache.get(sid)


def get_session_file_uuids(sid: str) -> set:
    """Return the set of file_uuids uploaded in this session."""
    with _session_lock:
        idx = _session_cache.get(sid)
    if idx is None:
        return set()
    return set(idx.file_uuids)


def remove_session(sid: str) -> None:
    """Evict all data for a session."""
    with _session_lock:
        _session_cache.pop(sid, None)


def cleanup_expired(max_age_seconds: int = 7200) -> int:
    """Evict sessions whose last_accessed exceeds *max_age_seconds*.

    Returns the number of evicted sessions.
    """
    now = time.time()
    to_evict = []
    with _session_lock:
        for sid, idx in _session_cache.items():
            if now - idx.last_accessed > max_age_seconds:
                to_evict.append(sid)
        for sid in to_evict:
            del _session_cache[sid]
    return len(to_evict)
