"""Long-lived embedding and hybrid-retrieval adapter for the web API."""

from __future__ import annotations

from typing import Any

from pgvector.psycopg2 import register_vector
from sentence_transformers import SentenceTransformer
from src.lib.softmaxx.boxgpt.rag import _normalize_embedding, apply_mmr_filter

from .database import transaction


class RagAdapter:
    def __init__(self, model_name: str, device: str | None = None):
        # Construct once in the API lifespan, then reuse for every request.
        self.model = SentenceTransformer(model_name, device=device)

    def retrieve(
        self,
        question: str,
        limit: int = 5,
        candidates: int = 20,
        doc_id: str | None = None,
    ) -> list[dict[str, Any]]:
        query_vector = self.model.encode(question, normalize_embeddings=True).tolist()
        if len(query_vector) != 1024:
            raise RuntimeError(f"BGE-M3 must return 1024 dimensions; got {len(query_vector)}")

        vector_filter = "WHERE c.doc_id = %s" if doc_id else ""
        keyword_filter = "AND c.doc_id = %s" if doc_id else ""
        vector_params = (query_vector, doc_id, query_vector, candidates) if doc_id else (
            query_vector, query_vector, candidates
        )
        keyword_params = (question, question, doc_id, candidates) if doc_id else (
            question, question, candidates
        )
        with transaction() as connection:
            register_vector(connection)
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT c.id, c.doc_id, d.source_filename, d.document_type,
                           d.metadata->>'title' AS display_title,
                           c.section_title, c.page_start, c.page_end, c.content, c.embedding,
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
                cursor.execute(
                    f"""
                    SELECT c.id, c.doc_id, d.source_filename, d.document_type,
                           d.metadata->>'title' AS display_title,
                           c.section_title, c.page_start, c.page_end, c.content, c.embedding,
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
                    ORDER BY keyword_score DESC
                    LIMIT %s
                    """,
                    keyword_params,
                )
                keyword_rows = cursor.fetchall()

        fused: dict[int, dict[str, Any]] = {}
        for rank, row in enumerate(vector_rows, start=1):
            chunk_id, doc_id, filename, doc_type, title, section, page_start, page_end, content, embedding, similarity = row
            fused[chunk_id] = {
                "id": chunk_id,
                "doc_id": doc_id,
                "filename": filename,
                "title": title or filename,
                "document_type": doc_type,
                "section": section,
                "page_start": page_start,
                "page_end": page_end,
                "content": content,
                "embedding": _normalize_embedding(embedding),
                "vector_rank": rank,
                "similarity": float(similarity),
                "rrf": 1 / (60 + rank),
            }
        for rank, row in enumerate(keyword_rows, start=1):
            chunk_id, doc_id, filename, doc_type, title, section, page_start, page_end, content, embedding, keyword_score = row
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
                    "content": content,
                    "embedding": _normalize_embedding(embedding),
                    "rrf": 0.0,
                },
            )
            result["keyword_rank"] = rank
            result["keyword_score"] = float(keyword_score)
            result["rrf"] += 1 / (60 + rank)

        # Rajiv's MMR implementation diversifies the RRF-ranked candidate pool so
        # near-duplicate passages do not consume all of the final source slots.
        ranked = sorted(fused.values(), key=lambda item: item["rrf"], reverse=True)[:candidates]
        ordered = apply_mmr_filter(
            candidates=ranked,
            query_embedding=query_vector,
            final_top_k=limit,
            lambda_param=0.7,
        )
        for index, item in enumerate(ordered, start=1):
            item["mmr_rank"] = index
            item["citation"] = f"S{index}"
        return ordered
