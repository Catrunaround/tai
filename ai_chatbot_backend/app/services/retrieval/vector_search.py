# Standard python libraries
import json
import pickle
import threading
import time
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING
from uuid import UUID

# Third-party libraries
import numpy as np

# Local libraries
from app.services.retrieval.embedding import (
    _get_embedding, _get_cursor, _decode_vec_from_db,
    EMBEDDING_PICKLE_PATH, SQLDB,
)
from app.services.retrieval.course_mapping import _get_pickle_and_class

if TYPE_CHECKING:
    from app.services.request_timer import RequestTimer

_course_cache = {}
_course_lock = threading.Lock()


def get_reference_documents(
    query: str, course: str, top_k: int, timer: Optional["RequestTimer"] = None
) -> Tuple[Tuple[List[str], List[str], List[str], List[float], List[str], List[str], List[str]], str]:
    """
    Retrieve top reference documents based on the query embedding and choice of DB-type.
    """
    class_name = _get_pickle_and_class(course)

    # Mark embedding start
    if timer:
        timer.mark("embedding_start")
    t0 = time.time()

    query_embed = {"dense_vecs": _get_embedding(query)}

    # Mark embedding end
    if timer:
        timer.mark("embedding_end")
    print(f"[INFO] Embedding time: {time.time() - t0:.2f} seconds")

    # Mark retrieval start
    if timer:
        timer.mark("retrieval_start")
    t1 = time.time()

    if SQLDB:
        output = _get_references_from_sql(query_embed, course, top_k=top_k)

    # Mark retrieval end
    if timer:
        timer.mark("retrieval_end")
    print(f"[INFO] Retrieval time: {time.time() - t1:.2f} seconds")

    return output, class_name


def get_chunks_by_file_uuid(file_uuid: UUID) -> List[Dict[int, Any]]:
    """
    Get all chunks associated with a specific file UUID.
    """
    with _get_cursor() as cur:
        rows = cur.execute("""
            SELECT `idx`, `text`
            FROM chunks
            WHERE file_uuid = ?
            ORDER BY `chunk_index`;
        """, (str(file_uuid),)).fetchall()
    return [{"index": row["idx"], "chunk": row["text"]} for row in rows]

def get_sections_by_file_uuid(file_uuid: UUID) -> List[Dict[int, Any]]:
    """
    Get all sections associated with a specific file UUID.
    """
    with _get_cursor() as cur:
        rows = cur.execute("""
            SELECT `sections`
            FROM file
            WHERE uuid = ?;
        """, (str(file_uuid),)).fetchone()
        sections = json.loads(rows["sections"]) if rows and rows["sections"] else []
    return sections

def get_file_related_documents(
    file_uuid: UUID, course: str, top_k: int
) -> Tuple[List[str], List[str], List[str], List[float], List[str], List[str], List[str], List[str], List[float]]:
    """
    Retrieve top related documents for a specific file UUID.
    """
    # Get the file embedding by file uuid
    with _get_cursor() as cur:
        row = cur.execute("""
            SELECT `uuid`, `vector`
            FROM file
            WHERE uuid = ?
        """, (str(file_uuid),)).fetchone()
    file_embedding = row["vector"] if row else None
    if not file_embedding:
        raise ValueError(f"File with UUID {file_uuid} not found or has no embedding.")

    query_embed = {"dense_vecs": _decode_vec_from_db(file_embedding)}
    return _get_references_from_sql(query_embed, course, top_k)

def _get_references_from_sql(
    query_embed: Dict[str, Any], course: str, top_k: int
) -> Tuple[List[str], List[str], List[str], List[float], List[str], List[str], List[str], List[str], List[float]]:
    """
    Retrieve top reference documents from a SQL database.
    """
    # Convert the query embedding to a numpy array
    qv = np.array(query_embed["dense_vecs"], dtype=np.float32).reshape(-1)
    if qv.size == 0:
        return [], [], [], [], [], [], [],[], []
    # Get the course index from the cache or build it if not present or stale
    idx = _get_course_index(course)
    if not idx.get("M") is not None:
        return [], [], [], [], [], [], [],[], []
    # Compute the scores for each document in the index
    document_matrix = idx["M"]
    scores = document_matrix @ qv
    k = min(top_k, document_matrix.shape[0])
    top_idx = np.argpartition(scores, -k)[-k:]
    top_idx = top_idx[np.argsort(scores[top_idx])[::-1]]
    # Extract the top-k results
    top_chunk_uuids = [idx["chunk_uuids"][i] for i in top_idx]
    top_texts = [idx["texts"][i] for i in top_idx]
    top_urls = [idx["urls"][i] for i in top_idx]
    top_scores = [float(scores[i]) for i in top_idx]
    top_file_paths = [idx["file_paths"][i] for i in top_idx]
    top_reference_paths = [idx["reference_paths"][i] for i in top_idx]
    top_titles = [idx["titles"][i] for i in top_idx]
    top_file_uuids = [idx["file_uuids"][i] for i in top_idx]
    top_chunk_idxs = [idx["chunk_idxs"][i] for i in top_idx]
    return top_chunk_uuids, top_texts, top_urls, top_scores, top_file_paths, top_reference_paths, top_titles, top_file_uuids, top_chunk_idxs


def _get_course_index(course: str):
    """
    Get the course index from the cache or build it if not present or stale.
    """
    with _course_lock:
        idx = _course_cache.get(course)
    # check staleness
    with _get_cursor() as cur:
        dv_now = cur.execute("PRAGMA data_version").fetchone()[0]
    if idx is None or idx["dv"] != dv_now or idx.get("M") is None:
        idx = _build_course_index(course)
        with _course_lock:
            _course_cache[course] = idx
    return idx


def _build_course_index(course: str):
    """
    Build an index of all chunks in the database for a specific course.
    """
    # Prepare connection params to the SQLite database
    where = "WHERE vector IS NOT NULL"
    params = []
    if course and course != "general":
        where += " AND course_code = ?"
        params.append(course)
    # Use a context manager to get SQL-DB cursor to ensure the connection is closed properly
    with _get_cursor() as cur:
        dv = cur.execute("PRAGMA data_version").fetchone()[0]
        rows = cur.execute(f"""
            SELECT chunk_uuid, file_path, reference_path, vector, title, text, url, file_uuid, idx
            FROM chunks
            {where};
        """, params).fetchall()
    # Process the rows fetched from the database
    chunk_uuids, file_paths, reference_paths, titles, texts, urls, vectors, file_uuids, chunk_idxs = [], [], [], [], [], [], [], [], []
    dim = None
    for r in rows:
        v = _decode_vec_from_db(r["vector"])
        if v is None:
            continue
        if dim is None:
            dim = v.size
        if v.size != dim:
            continue
        chunk_uuids.append(r["chunk_uuid"])
        file_paths.append(r["file_path"] or "")
        reference_paths.append(r["reference_path"] or "")
        titles.append(r["title"] or "")
        texts.append(r["text"] or "")
        urls.append(r["url"] or "")
        vectors.append(v.astype(np.float32, copy=False))
        file_uuids.append(r["file_uuid"] or "")
        chunk_idxs.append(r["idx"] if r["idx"] is not None else 0)
    if not vectors:
        return {"dv": dv, "M": None}
    # Stack the vectors to compute scores later
    document_matrix = np.vstack(vectors)  # shape: [N, D]
    return {
        "dv": dv, "chunk_uuids": chunk_uuids, "file_paths": file_paths, "reference_paths": reference_paths,
        "titles": titles, "texts": texts, "urls": urls, "M": document_matrix, "file_uuids": file_uuids, "chunk_idxs": chunk_idxs
    }


def _get_references_from_pickle(
    query_embed: Dict[str, Any], pickle_file: str, top_k: int
) -> Tuple[List[str], List[str], List[str], List[float], List[str], List[str], List[str]]:
    """
    Retrieve top reference documents from a pickle file.
    """
    # Load the pickle file content
    path_to_pickle = EMBEDDING_PICKLE_PATH / pickle_file
    with open(path_to_pickle, "rb") as f:
        data_loaded = pickle.load(f)
    doc_list = data_loaded["doc_list"]
    file_path_list = data_loaded["file_paths_list"]
    topic_path_list = data_loaded["topic_path_list"]
    id_list = data_loaded["id_list"]
    url_list = data_loaded["url_list"]
    embedding_list = data_loaded["embedding_list"]
    # Compute the similarity scores
    score = query_embed["dense_vecs"] @ embedding_list["dense_vecs"].T
    score_array = np.array(score)
    # Sort the scores and retrieve the top_k results
    indices = np.argsort(score_array)[::-1]
    similarity_scores = np.sort(score_array)[-top_k:][::-1]
    top_ids = id_list[indices][:top_k]
    top_docs = doc_list[indices][:top_k]
    top_files = file_path_list[indices][:top_k]
    top_topic_paths = topic_path_list[indices][:top_k]
    top_urls = url_list[indices][:top_k].tolist()
    # TODO: Add top_titles if available in the pickle file
    top_titles = []
    return top_ids, top_docs, top_urls, similarity_scores, top_files, top_topic_paths, top_titles
