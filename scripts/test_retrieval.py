"""Run a one-question hybrid retrieval check against the local Postgres corpus."""

import argparse
import json
from pathlib import Path
from typing import Any

import psycopg2
from pgvector.psycopg2 import register_vector
from sentence_transformers import SentenceTransformer


def database_config(path: Path) -> dict[str, Any]:
    config = json.loads(path.read_text(encoding="utf-8"))
    database = config["database"]["default"]
    return {
        "host": database["host"],
        "port": database["port"],
        "user": database["user"],
        "password": database["password"],
        "dbname": database.get("database", database.get("dbname")),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("question", help="Question to test against the indexed Markdown documents")
    parser.add_argument("--config", type=Path, default=Path("config.json"))
    parser.add_argument("--model", default="BAAI/bge-m3")
    parser.add_argument("--limit", type=int, default=5, help="Number of final chunks to display")
    parser.add_argument("--candidates", type=int, default=20, help="Candidates per retrieval method")
    args = parser.parse_args()

    model = SentenceTransformer(args.model)
    query_vector = model.encode(args.question, normalize_embeddings=True).tolist()
    if len(query_vector) != 1024:
        raise ValueError(f"Expected a 1024-dimensional BGE-M3 vector; got {len(query_vector)}")

    connection = psycopg2.connect(**database_config(args.config))
    register_vector(connection)
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT c.id, c.doc_id, d.source_filename, d.document_type,
                       c.section_title, c.page_start, c.page_end, c.content,
                       1 - (c.embedding <=> %s::vector) AS similarity
                FROM document_chunks c JOIN documents d USING (doc_id)
                ORDER BY c.embedding <=> %s::vector
                LIMIT %s
                """,
                (query_vector, query_vector, args.candidates),
            )
            vector_rows = cursor.fetchall()
            cursor.execute(
                """
                SELECT c.id, c.doc_id, d.source_filename, d.document_type,
                       c.section_title, c.page_start, c.page_end, c.content,
                       ts_rank_cd(to_tsvector('simple', c.content),
                                  plainto_tsquery('simple', %s)) AS keyword_score
                FROM document_chunks c JOIN documents d USING (doc_id)
                WHERE to_tsvector('simple', c.content) @@ plainto_tsquery('simple', %s)
                ORDER BY keyword_score DESC
                LIMIT %s
                """,
                (args.question, args.question, args.candidates),
            )
            keyword_rows = cursor.fetchall()
    finally:
        connection.close()

    # Reciprocal Rank Fusion rewards chunks that rank well in either or both lists.
    ranked: dict[int, dict[str, Any]] = {}
    for rank, row in enumerate(vector_rows, start=1):
        chunk_id, doc_id, filename, doc_type, section, page_start, page_end, content, similarity = row
        ranked[chunk_id] = {
            "id": chunk_id,
            "doc_id": doc_id,
            "filename": filename,
            "doc_type": doc_type,
            "section": section,
            "page_start": page_start,
            "page_end": page_end,
            "content": content,
            "vector_rank": rank,
            "similarity": float(similarity),
            "rrf": 1 / (60 + rank),
        }
    for rank, row in enumerate(keyword_rows, start=1):
        chunk_id, doc_id, filename, doc_type, section, page_start, page_end, content, score = row
        result = ranked.setdefault(
            chunk_id,
            {
                "id": chunk_id,
                "doc_id": doc_id,
                "filename": filename,
                "doc_type": doc_type,
                "section": section,
                "page_start": page_start,
                "page_end": page_end,
                "content": content,
            },
        )
        result["keyword_rank"] = rank
        result["keyword_score"] = float(score)
        result["rrf"] = result.get("rrf", 0.0) + 1 / (60 + rank)

    results = sorted(ranked.values(), key=lambda item: item["rrf"], reverse=True)[: args.limit]
    print(f"Question: {args.question}\n")
    if not results:
        print("No matching chunks found.")
        return
    for index, result in enumerate(results, start=1):
        page = result.get("page_start")
        page_label = f"page {page}" if page is not None else "page not tagged"
        print(f"[{index}] {result['filename']} | {result['doc_type']} | {page_label}")
        print(f"    Section: {result['section']} | RRF: {result['rrf']:.5f}")
        print(
            f"    Vector rank: {result.get('vector_rank', '—')} | "
            f"Keyword rank: {result.get('keyword_rank', '—')}"
        )
        print(f"    {result['content']}\n")


if __name__ == "__main__":
    main()
