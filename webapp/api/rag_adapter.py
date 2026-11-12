"""Long-lived embedding and hybrid-retrieval adapter for the web API."""

from __future__ import annotations

import time
import re
from typing import Any

from pgvector.psycopg2 import register_vector
from sentence_transformers import SentenceTransformer
from src.lib.softmaxx.boxgpt.rag import _normalize_embedding, apply_mmr_filter

from .database import transaction


class RagAdapter:
    def __init__(
        self,
        model_name: str,
        device: str | None = None,
        final_results: int = 4,
        candidates: int = 24,
        mmr_lambda: float = 0.72,
        vector_weight: float = 1.0,
        lexical_weight: float = 1.35,
        lexical_reserved_slots: int = 1,
        rrf_k: int = 60,
        neighbor_expansion: bool = True,
        neighbor_top_results: int = 2,
        neighbor_distance: int = 1,
        max_context_chunks: int = 8,
    ):
        if final_results < 1:
            raise ValueError("final_results must be positive")
        if candidates < final_results:
            raise ValueError("candidates must be at least final_results")
        if not 0 <= mmr_lambda <= 1:
            raise ValueError("mmr_lambda must be between 0 and 1")
        if vector_weight <= 0 or lexical_weight <= 0:
            raise ValueError("RRF weights must be positive")
        if not 0 <= lexical_reserved_slots <= final_results:
            raise ValueError("lexical_reserved_slots must be between 0 and final_results")
        if rrf_k < 1:
            raise ValueError("rrf_k must be positive")
        if neighbor_top_results < 0 or neighbor_distance < 0:
            raise ValueError("neighbor settings cannot be negative")
        if max_context_chunks < final_results:
            raise ValueError("max_context_chunks must be at least final_results")

        # Construct once in the API lifespan, then reuse for every request.
        self.model = SentenceTransformer(model_name, device=device)
        self.final_results = final_results
        self.candidates = candidates
        self.mmr_lambda = mmr_lambda
        self.vector_weight = vector_weight
        self.lexical_weight = lexical_weight
        self.lexical_reserved_slots = lexical_reserved_slots
        self.rrf_k = rrf_k
        self.neighbor_expansion = neighbor_expansion
        self.neighbor_top_results = neighbor_top_results
        self.neighbor_distance = neighbor_distance
        self.max_context_chunks = max_context_chunks

    def retrieve(
        self,
        question: str,
        limit: int | None = None,
        candidates: int | None = None,
        doc_id: str | None = None,
    ) -> list[dict[str, Any]]:
        results, _ = self.retrieve_with_metrics(question, limit, candidates, doc_id)
        return results

    def retrieve_with_metrics(
        self,
        question: str,
        limit: int | None = None,
        candidates: int | None = None,
        doc_id: str | None = None,
    ) -> tuple[list[dict[str, Any]], dict[str, int]]:
        """Retrieve passages and return server-side stage timings in milliseconds."""
        retrieval_started = time.perf_counter()
        limit = limit or self.final_results
        candidates = candidates or self.candidates
        stage_started = time.perf_counter()
        query_vector = self.model.encode(question, normalize_embeddings=True).tolist()
        embedding_ms = _elapsed_ms(stage_started)
        if len(query_vector) != 1024:
            raise RuntimeError(f"BGE-M3 must return 1024 dimensions; got {len(query_vector)}")

        vector_filter = "WHERE c.doc_id = %s" if doc_id else ""
        keyword_filter = "AND c.doc_id = %s" if doc_id else ""
        lexical_terms = extract_lexical_terms(question)
        lexical_query = " OR ".join(lexical_terms)
        lexical_pool = max(candidates * 4, candidates)
        vector_params = (query_vector, doc_id, query_vector, candidates) if doc_id else (
            query_vector, query_vector, candidates
        )
        keyword_params = (lexical_query, lexical_query, doc_id, lexical_pool) if doc_id else (
            lexical_query, lexical_query, lexical_pool
        )
        with transaction() as connection:
            register_vector(connection)
            with connection.cursor() as cursor:
                stage_started = time.perf_counter()
                cursor.execute(
                    f"""
                    SELECT c.id, c.doc_id, d.source_filename, d.document_type,
                           d.metadata->>'title' AS display_title,
                           c.section_title, c.page_start, c.page_end, c.chunk_index,
                           c.content, c.embedding,
                           1 - (c.embedding <=> %s::vector) AS similarity
                    FROM document_chunks c
                    JOIN documents d USING (doc_id)
                    {vector_filter}
                    ORDER BY c.embedding <=> %s::vector
                    LIMIT %s
                    """,
                    vector_params,
                )
                vector_rows = cursor.fetchall()
                vector_search_ms = _elapsed_ms(stage_started)
                stage_started = time.perf_counter()
                cursor.execute(
                    f"""
                    SELECT c.id, c.doc_id, d.source_filename, d.document_type,
                           d.metadata->>'title' AS display_title,
                           c.section_title, c.page_start, c.page_end, c.chunk_index,
                           c.content, c.embedding,
                           ts_rank_cd(
                               setweight(to_tsvector('english', COALESCE(d.metadata->>'title', d.source_filename)), 'A') ||
                               setweight(to_tsvector('english', COALESCE(c.section_title, '')), 'A') ||
                               setweight(to_tsvector('english', c.content), 'B'),
                               websearch_to_tsquery('english', %s)
                           ) AS keyword_score
                    FROM document_chunks c
                    JOIN documents d USING (doc_id)
                    WHERE (
                              setweight(to_tsvector('english', COALESCE(d.metadata->>'title', d.source_filename)), 'A') ||
                              setweight(to_tsvector('english', COALESCE(c.section_title, '')), 'A') ||
                              setweight(to_tsvector('english', c.content), 'B')
                          ) @@ websearch_to_tsquery('english', %s)
                    {keyword_filter}
                    ORDER BY keyword_score DESC, c.id
                    LIMIT %s
                    """,
                    keyword_params,
                )
                keyword_rows = cursor.fetchall()
                keyword_rows.sort(
                    key=lambda row: lexical_coverage_rank(row, lexical_terms), reverse=True
                )
                keyword_rows = keyword_rows[:candidates]
                lexical_search_ms = _elapsed_ms(stage_started)

        stage_started = time.perf_counter()
        fused: dict[int, dict[str, Any]] = {}
        for rank, row in enumerate(vector_rows, start=1):
            chunk_id, doc_id, filename, doc_type, title, section, page_start, page_end, chunk_index, content, embedding, similarity = row
            fused[chunk_id] = {
                "id": chunk_id,
                "doc_id": doc_id,
                "filename": filename,
                "title": title or filename,
                "document_type": doc_type,
                "section": section,
                "page_start": page_start,
                "page_end": page_end,
                "chunk_index": chunk_index,
                "content": content,
                "embedding": _normalize_embedding(embedding),
                "vector_rank": rank,
                "similarity": float(similarity),
                "rrf": self.vector_weight / (self.rrf_k + rank),
            }
        for rank, row in enumerate(keyword_rows, start=1):
            chunk_id, doc_id, filename, doc_type, title, section, page_start, page_end, chunk_index, content, embedding, keyword_score = row
            result = fused.setdefault(
                chunk_id,
                {
                    "id": chunk_id,
                    "doc_id": doc_id,
                    "filename": filename,
                    "title": title or filename,
                    "document_type": doc_type,
                    "section": section,
                    "page_start": page_start,
                    "page_end": page_end,
                    "chunk_index": chunk_index,
                    "content": content,
                    "embedding": _normalize_embedding(embedding),
                    "rrf": 0.0,
                },
            )
            result["keyword_rank"] = rank
            result["keyword_score"] = float(keyword_score)
            title_matches, matched_terms, _score, _stable_id = lexical_coverage_rank(
                row, lexical_terms
            )
            result["lexical_title_matches"] = title_matches
            result["lexical_matched_terms"] = matched_terms
            result["rrf"] += self.lexical_weight / (self.rrf_k + rank)

        ordered = select_hybrid_results(
            fused=fused,
            keyword_chunk_ids=[row[0] for row in keyword_rows],
            query_vector=query_vector,
            limit=limit,
            candidates=candidates,
            mmr_lambda=self.mmr_lambda,
            lexical_reserved_slots=self.lexical_reserved_slots,
        )
        fusion_mmr_ms = _elapsed_ms(stage_started)
        neighbor_expansion_ms = 0
        if self.neighbor_expansion and self.neighbor_top_results and self.neighbor_distance:
            neighbor_started = time.perf_counter()
            neighbors = self._load_neighbors(ordered[: self.neighbor_top_results])
            ordered = merge_neighbor_results(ordered, neighbors, self.max_context_chunks)
            neighbor_expansion_ms = _elapsed_ms(neighbor_started)
        for index, item in enumerate(ordered, start=1):
            item["mmr_rank"] = index
            item["citation"] = f"S{index}"
        return ordered, {
            "embedding_ms": embedding_ms,
            "vector_search_ms": vector_search_ms,
            "lexical_search_ms": lexical_search_ms,
            "fusion_mmr_ms": fusion_mmr_ms,
            "neighbor_expansion_ms": neighbor_expansion_ms,
            "retrieval_total_ms": _elapsed_ms(retrieval_started),
        }

    def _load_neighbors(self, seeds: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Load nearby chunks from the same document using stored chunk order."""
        if not seeds:
            return []
        neighbors: list[dict[str, Any]] = []
        with transaction() as connection:
            with connection.cursor() as cursor:
                for seed_rank, seed in enumerate(seeds, start=1):
                    cursor.execute(
                        """
                        SELECT c.id, c.doc_id, d.source_filename, d.document_type,
                               d.metadata->>'title', c.section_title, c.page_start,
                               c.page_end, c.chunk_index, c.content
                        FROM document_chunks c
                        JOIN documents d USING (doc_id)
                        WHERE c.doc_id = %s
                          AND c.chunk_index BETWEEN %s AND %s
                          AND c.id <> %s
                        ORDER BY ABS(c.chunk_index - %s), c.chunk_index, c.id
                        """,
                        (
                            seed["doc_id"], seed["chunk_index"] - self.neighbor_distance,
                            seed["chunk_index"] + self.neighbor_distance, seed["id"],
                            seed["chunk_index"],
                        ),
                    )
                    for row in cursor.fetchall():
                        chunk_id, doc_id, filename, doc_type, title, section, page_start, page_end, chunk_index, content = row
                        neighbors.append({
                            "id": chunk_id,
                            "doc_id": doc_id,
                            "filename": filename,
                            "title": title or filename,
                            "document_type": doc_type,
                            "section": section,
                            "page_start": page_start,
                            "page_end": page_end,
                            "chunk_index": chunk_index,
                            "content": content,
                            "selection_reason": "neighbor",
                            "neighbor_of": seed["id"],
                            "neighbor_seed_rank": seed_rank,
                        })
        return neighbors


def _elapsed_ms(started: float) -> int:
    return max(0, round((time.perf_counter() - started) * 1000))


_LEXICAL_IGNORED_WORDS = {
    "a", "an", "and", "are", "can", "could", "do", "does", "for", "from", "give",
    "how", "i", "in", "is", "it", "list", "me", "of", "on", "please", "provide",
    "required", "tell", "the", "this", "to", "us", "what", "when", "which", "who",
    "why", "with", "would", "whjat",
}


def build_relaxed_lexical_query(question: str) -> str:
    """Build an OR query so one typo or missing term cannot eliminate every match."""
    return " OR ".join(extract_lexical_terms(question))


def extract_lexical_terms(question: str) -> list[str]:
    """Extract distinct content terms used for relaxed matching and coverage ranking."""
    tokens = re.findall(r"[a-zA-Z0-9]+", question.lower())
    useful = list(dict.fromkeys(
        token for token in tokens if len(token) > 1 and token not in _LEXICAL_IGNORED_WORDS
    ))
    if not useful:
        useful = list(dict.fromkeys(token for token in tokens if len(token) > 1))
    return useful


def lexical_coverage_rank(row: tuple[Any, ...], terms: list[str]) -> tuple[int, int, float, int]:
    """Prefer broad term coverage and title matches over one frequently repeated term."""
    title_tokens = _normalized_word_roots(str(row[4] or row[2]))
    full_tokens = title_tokens | _normalized_word_roots(str(row[5] or "")) | _normalized_word_roots(str(row[9] or ""))
    term_roots = [_word_root(term) for term in terms]
    title_matches = sum(root in title_tokens for root in term_roots)
    matched_terms = sum(root in full_tokens for root in term_roots)
    return title_matches, matched_terms, float(row[11]), -int(row[0])


def _normalized_word_roots(text: str) -> set[str]:
    return {_word_root(token) for token in re.findall(r"[a-zA-Z0-9]+", text.lower())}


def _word_root(token: str) -> str:
    return token[:5] if len(token) > 5 else token


def merge_neighbor_results(
    base_results: list[dict[str, Any]],
    neighbors: list[dict[str, Any]],
    max_context_chunks: int,
) -> list[dict[str, Any]]:
    """Append neighbors without duplicates while preserving every primary result."""
    merged: list[dict[str, Any]] = []
    seen: set[int] = set()
    for item in base_results + neighbors:
        if item["id"] in seen:
            continue
        seen.add(item["id"])
        merged.append(item)
        if len(merged) >= max_context_chunks:
            break
    return merged


def select_hybrid_results(
    fused: dict[int, dict[str, Any]],
    keyword_chunk_ids: list[int],
    query_vector: list[float],
    limit: int,
    candidates: int,
    mmr_lambda: float,
    lexical_reserved_slots: int,
) -> list[dict[str, Any]]:
    """Keep strong lexical evidence, then use Rajiv's MMR for diversity."""
    if not fused or limit < 1:
        return []

    reserved: list[dict[str, Any]] = []
    reserved_ids: set[int] = set()
    for chunk_id in keyword_chunk_ids:
        if chunk_id not in fused or chunk_id in reserved_ids:
            continue
        item = fused[chunk_id]
        item["selection_reason"] = "lexical_reserved"
        reserved.append(item)
        reserved_ids.add(chunk_id)
        if len(reserved) >= min(lexical_reserved_slots, limit):
            break

    ranked = sorted(fused.values(), key=lambda item: item["rrf"], reverse=True)
    mmr_candidates = [item for item in ranked if item["id"] not in reserved_ids][:candidates]
    mmr_results = apply_mmr_filter(
        candidates=mmr_candidates,
        query_embedding=query_vector,
        final_top_k=max(0, limit - len(reserved)),
        lambda_param=mmr_lambda,
    )
    for item in mmr_results:
        item["selection_reason"] = "mmr"

    return (reserved + mmr_results)[:limit]
