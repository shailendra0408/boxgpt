"""Chunk preprocessed Markdown, embed it with BGE-M3, and store it in Postgres."""

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

import psycopg2
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pgvector.psycopg2 import register_vector
from psycopg2.extras import execute_values
from sentence_transformers import SentenceTransformer


PAGE_MARKER = re.compile(r"(?m)^---\s*Page\s+(\d+)\s*---\s*$", re.IGNORECASE)
HEADING = re.compile(r"^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$")
DOC_NUMBER = re.compile(
    r"(?im)\bDocument\s*(?:No\.?|Number)(?:\*\*)?\s*:?\s*(?:\*\*)?\s*(?:\|\s*)?\[?\s*"
    r"([A-Z0-9][A-Z0-9/&._-]*(?:[ \t]+[A-Z0-9][A-Z0-9/&._-]*){0,2})"
)


def _normal_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", Path(value).stem.lower())


def _metadata_from_markdown(path: Path, text: str) -> dict[str, Any]:
    title_match = re.search(r"(?im)(?:\*\*)?Title(?:\*\*)?\s*:\s*([^\n|]+)", text)
    number_match = next(
        (match for match in DOC_NUMBER.finditer(text) if "/" in match.group(1)),
        None,
    )
    issue_match = re.search(r"(?im)(?:\*\*)?Issue Date(?:\*\*)?\s*:\s*([^\n|]+)", text)

    sample = f"{path.stem}\n{text[:10000]}".lower()
    if "red corner notice" in sample or re.search(r"\bRCN\s*[/#]", sample):
        document_type = "RCN"
    elif "blue corner notice" in sample or re.search(r"\bBCN\s*[/#]", sample):
        document_type = "BCN"
    elif (
        "safe work procedure" in sample
        or path.stem.lower().startswith(("swp_", "swp-"))
        or re.search(r"\bSWP\s*[/#]", sample)
    ):
        document_type = "SWP"
    elif (
        "standard operating procedure" in sample
        or path.stem.lower().startswith(("sop_", "sop-"))
        or re.search(r"\bSOP\s*[/#]", sample)
    ):
        document_type = "SOP"
    elif "standard maintenance procedure" in sample or re.search(r"\bSMP\s*[/#]", sample):
        document_type = "SMP"
    else:
        document_type = "UNKNOWN"

    return {
        "title": title_match.group(1).strip().strip("* ") if title_match else path.stem,
        "document_number": number_match.group(1).rstrip(".,;:*") if number_match else None,
        "issue_date": issue_match.group(1).strip().strip("* ") if issue_match else None,
        "document_type": document_type,
        "source_markdown": path.name,
    }


def _strip_front_matter_and_metadata(text: str) -> str:
    text = text.lstrip("\ufeff\n")
    if text.startswith("---\n"):
        closing = text.find("\n---", 4)
        if closing >= 0:
            text = text[closing + 4 :]
    content_header = re.search(r"(?im)^#\s+DOCUMENT CONTENT\s*$", text)
    if content_header:
        text = text[content_header.end() :]
    return text.strip()


def _sections_for_page(text: str, page_number: int | None) -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = []
    current_title = f"Page {page_number} - General" if page_number else "General"
    current_lines: list[str] = []

    def emit() -> None:
        content = "\n".join(current_lines).strip()
        content = re.sub(r"(?m)^---\s*$", "", content).strip()
        if content:
            is_postprocessed_summary = current_title.upper() in {
                "PPE MATRICES",
                "UNIQUE PPE LIST",
            }
            sections.append({
                "section_title": current_title,
                "page_start": None if is_postprocessed_summary else page_number,
                "page_end": None if is_postprocessed_summary else page_number,
                "content": content,
            })

    for line in text.splitlines():
        match = HEADING.match(line)
        if match:
            emit()
            current_title = match.group(2).strip()
            current_lines = []
        else:
            current_lines.append(line)
    emit()
    return sections


def parse_markdown_sections(text: str) -> list[dict[str, Any]]:
    """Split Rajiv-style Markdown at page markers and headings, keeping provenance."""
    body = _strip_front_matter_and_metadata(text)
    matches = list(PAGE_MARKER.finditer(body))
    if not matches:
        return _sections_for_page(body, 1)

    sections: list[dict[str, Any]] = []
    for index, marker in enumerate(matches):
        page_number = int(marker.group(1))
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        page_text = body[marker.end() : end].strip()
        sections.extend(_sections_for_page(page_text, page_number))
    return sections


def _split_table(content: str, max_chars: int) -> list[str] | None:
    lines = [line.rstrip() for line in content.splitlines() if line.strip()]
    if len(lines) < 3 or not lines[0].lstrip().startswith("|") or "---" not in lines[1]:
        return None

    header = lines[:2]
    header_text = "\n".join(header)
    chunks: list[str] = []
    rows: list[str] = []
    size = len(header_text)
    for row in lines[2:]:
        if not row.lstrip().startswith("|"):
            return None
        if rows and size + len(row) + 1 > max_chars:
            chunks.append(header_text + "\n" + "\n".join(rows))
            rows = []
            size = len(header_text)
        rows.append(row)
        size += len(row) + 1
    if rows:
        chunks.append(header_text + "\n" + "\n".join(rows))
    return chunks


def build_chunks(
    sections: list[dict[str, Any]],
    doc_id: str,
    metadata: dict[str, Any],
    max_chars: int,
    overlap: int,
) -> list[dict[str, Any]]:
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=max_chars,
        chunk_overlap=overlap,
        separators=["\n\n", "\n", "। ", ". ", " ", ""],
    )
    chunks: list[dict[str, Any]] = []

    for section in sections:
        content = section["content"].strip()
        table_chunks = _split_table(content, max_chars)
        section_chunks = table_chunks or (
            [content] if len(content) <= max_chars else splitter.split_text(content)
        )
        for chunk_text in section_chunks:
            page_start = section["page_start"]
            page_end = section["page_end"]
            context = [
                f"Document type: {metadata['document_type']}",
                f"Document title: {metadata['title']}",
                f"Section: {section['section_title']}",
            ]
            if metadata.get("document_number"):
                context.insert(1, f"Document number: {metadata['document_number']}")
            if page_start is not None:
                context.append(f"Page: {page_start}")
            chunks.append({
                "doc_id": doc_id,
                "section_title": section["section_title"],
                "page_start": page_start,
                "page_end": page_end,
                "chunk_index": len(chunks),
                "content": chunk_text,
                "embedding_text": "\n".join(context) + "\n\n" + chunk_text,
                "chunk_metadata": {
                    "document_type": metadata["document_type"],
                    "document_number": metadata.get("document_number"),
                    "title": metadata["title"],
                    "page_start": page_start,
                    "page_end": page_end,
                },
            })
    return chunks


def load_markdown_document(path: Path, max_chars: int, overlap: int) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    # Include the filename in identity: separate source documents can have
    # identical Markdown contents but must remain independently filterable.
    identity = hashlib.sha256(f"{path.name}\0{digest}".encode("utf-8")).hexdigest()
    doc_id = f"DOC_{identity[:16].upper()}"
    metadata = _metadata_from_markdown(path, text)
    sections = parse_markdown_sections(text)
    chunks = build_chunks(sections, doc_id, metadata, max_chars, overlap)
    if not chunks:
        raise ValueError("No searchable content was found")
    return {
        "doc_id": doc_id,
        "content_sha256": digest,
        "source_filename": path.name,
        "source_path": str(path.resolve()),
        "metadata": metadata,
        "sections": sections,
        "chunks": chunks,
    }


def _markdown_files(input_path: Path) -> list[Path]:
    if input_path.is_file() and input_path.suffix.lower() == ".md":
        return [input_path]
    if input_path.is_dir():
        return sorted(input_path.rglob("*.md"))
    raise FileNotFoundError(f"Markdown file or directory not found: {input_path}")


def preview(input_path: Path, output_dir: Path, max_chars: int, overlap: int) -> None:
    files = _markdown_files(input_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    failures = 0
    print(f"Found {len(files)} Markdown document(s).")
    for position, path in enumerate(files, start=1):
        try:
            doc = load_markdown_document(path, max_chars, overlap)
            target = output_dir / f"{path.stem}.json"
            payload = {
                "doc_id": doc["doc_id"],
                "source_filename": doc["source_filename"],
                "metadata": doc["metadata"],
                "chunk_count": len(doc["chunks"]),
                "settings": {"max_chars": max_chars, "overlap": overlap},
                "chunks": doc["chunks"],
            }
            temporary = target.with_suffix(".tmp")
            temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(target)
            print(f"[{position}/{len(files)}] {path.name}: {len(doc['chunks'])} chunks")
        except Exception as error:
            failures += 1
            print(f"FAILED: {path}: {error}")
    print(f"Preview complete: {len(files) - failures} succeeded; {failures} failed.")


def _database_config(config_path: Path) -> dict[str, Any]:
    if not config_path.exists():
        raise FileNotFoundError(f"Database configuration not found: {config_path}")
    config = json.loads(config_path.read_text(encoding="utf-8"))
    database = config["database"]["default"]
    return {
        "host": database["host"],
        "port": database["port"],
        "user": database["user"],
        "password": database["password"],
        "dbname": database.get("database", database.get("dbname")),
    }


def _existing_documents(cursor: Any) -> dict[tuple[str, str | None], dict[str, Any]]:
    cursor.execute(
        "SELECT doc_id, source_filename, source_path, content_sha256, document_type, metadata "
        "FROM documents"
    )
    return {
        (_normal_name(row[1]), row[3]): {
            "doc_id": row[0],
            "source_filename": row[1],
            "source_path": row[2],
            "content_sha256": row[3],
            "document_type": row[4],
            "metadata": row[5] or {},
        }
        for row in cursor.fetchall()
    }


def _store_document(cursor: Any, doc: dict[str, Any], existing: dict[str, Any] | None) -> int:
    doc_id = existing["doc_id"] if existing else doc["doc_id"]
    metadata = dict(existing["metadata"]) if existing else {}
    metadata.update(doc["metadata"])
    metadata["preprocessed_markdown_path"] = doc["source_path"]
    metadata["preprocessed_markdown_sha256"] = doc["content_sha256"]

    cursor.execute(
        """
        INSERT INTO documents (
            doc_id, source_filename, source_path, content_sha256,
            document_type, metadata, processing_status, processing_error
        ) VALUES (%s, %s, %s, %s, %s, %s::jsonb, 'processing', NULL)
        ON CONFLICT (doc_id) DO UPDATE SET
            source_filename = CASE
                WHEN documents.source_path IS NOT NULL THEN documents.source_filename
                ELSE EXCLUDED.source_filename
            END,
            source_path = COALESCE(documents.source_path, EXCLUDED.source_path),
            content_sha256 = COALESCE(documents.content_sha256, EXCLUDED.content_sha256),
            document_type = COALESCE(EXCLUDED.document_type, documents.document_type),
            metadata = documents.metadata || EXCLUDED.metadata,
            processing_status = 'processing',
            processing_error = NULL
        """,
        (
            doc_id,
            existing["source_filename"] if existing else doc["source_filename"],
            existing["source_path"] if existing else doc["source_path"],
            existing["content_sha256"] if existing else doc["content_sha256"],
            doc["metadata"]["document_type"],
            json.dumps(metadata, ensure_ascii=False),
        ),
    )
    cursor.execute("DELETE FROM document_chunks WHERE doc_id = %s", (doc_id,))

    values = [
        (
            doc_id,
            chunk["section_title"],
            chunk["page_start"],
            chunk["page_end"],
            chunk["chunk_index"],
            chunk["content"],
            chunk["embedding_text"],
            json.dumps(chunk["chunk_metadata"], ensure_ascii=False),
            chunk["embedding"],
        )
        for chunk in doc["chunks"]
    ]
    execute_values(
        cursor,
        """
        INSERT INTO document_chunks (
            doc_id, section_title, page_start, page_end, chunk_index,
            content, embedding_text, chunk_metadata, embedding
        ) VALUES %s
        """,
        values,
        template="(%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s)",
    )
    cursor.execute(
        "UPDATE documents SET processing_status = 'completed', processed_at = NOW() WHERE doc_id = %s",
        (doc_id,),
    )
    return len(values)


def ingest(
    input_path: Path,
    config_path: Path,
    model_name: str,
    max_chars: int,
    overlap: int,
    batch_size: int,
) -> None:
    files = _markdown_files(input_path)
    documents = [load_markdown_document(path, max_chars, overlap) for path in files]
    print(f"Prepared {len(documents)} document(s), {sum(len(d['chunks']) for d in documents)} chunks.")
    if not documents:
        return

    model = SentenceTransformer(model_name)
    all_chunks = [chunk for document in documents for chunk in document["chunks"]]
    embeddings = model.encode(
        [chunk["embedding_text"] for chunk in all_chunks],
        batch_size=batch_size,
        show_progress_bar=True,
        normalize_embeddings=True,
    )
    for chunk, embedding in zip(all_chunks, embeddings):
        if len(embedding) != 1024:
            raise ValueError(f"BGE-M3 returned {len(embedding)} dimensions; expected 1024")
        chunk["embedding"] = embedding.tolist()

    connection = psycopg2.connect(**_database_config(config_path))
    register_vector(connection)
    cursor = connection.cursor()
    try:
        existing_by_identity = _existing_documents(cursor)
        total_chunks = 0
        for index, document in enumerate(documents, start=1):
            identity = (
                _normal_name(document["source_filename"]),
                document["content_sha256"],
            )
            existing = existing_by_identity.get(identity)
            try:
                total_chunks += _store_document(cursor, document, existing)
                connection.commit()
                print(
                    f"[{index}/{len(documents)}] {document['source_filename']}: "
                    f"{len(document['chunks'])} chunks stored"
                    + (f" (updated {existing['doc_id']})" if existing else "")
                )
            except Exception as error:
                connection.rollback()
                print(f"FAILED: {document['source_filename']}: {error}")
        print(f"Ingestion complete. {total_chunks} chunks stored or refreshed.")
    finally:
        cursor.close()
        connection.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    preview_parser = subparsers.add_parser("preview", help="Create chunk JSON without database writes")
    preview_parser.add_argument("input", type=Path)
    preview_parser.add_argument("--output-dir", type=Path, default=Path("data/chunks/rajiv_preprocessed_json"))
    preview_parser.add_argument("--max-chars", type=int, default=1500)
    preview_parser.add_argument("--overlap", type=int, default=150)

    ingest_parser = subparsers.add_parser("ingest", help="Embed Markdown documents and store chunks in Postgres")
    ingest_parser.add_argument("input", type=Path)
    ingest_parser.add_argument("--config", type=Path, default=Path("config.json"))
    ingest_parser.add_argument("--model", default="BAAI/bge-m3")
    ingest_parser.add_argument("--max-chars", type=int, default=1500)
    ingest_parser.add_argument("--overlap", type=int, default=150)
    ingest_parser.add_argument("--batch-size", type=int, default=16)

    args = parser.parse_args()
    if args.max_chars < 1 or args.overlap < 0 or args.overlap >= args.max_chars:
        parser.error("--max-chars must be positive and --overlap must be between 0 and max-chars")
    if args.command == "preview":
        preview(args.input, args.output_dir, args.max_chars, args.overlap)
    else:
        ingest(args.input, args.config, args.model, args.max_chars, args.overlap, args.batch_size)


if __name__ == "__main__":
    main()
