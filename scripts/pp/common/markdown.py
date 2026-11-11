"""General Mistral OCR JSON to page-preserving Markdown conversion."""

import argparse
import json
from pathlib import Path
from typing import Any


def _unwrap_payload(payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Support both the application's wrapped OCR JSON and raw Mistral output."""
    document = payload.get("document", {})
    ocr_response = payload.get("ocr_response")
    if not isinstance(ocr_response, dict):
        ocr_response = payload
    if not isinstance(document, dict):
        document = {}
    return document, ocr_response


def _block_text(page: dict[str, Any]) -> str:
    lines: list[str] = []
    for block in page.get("blocks", []):
        if not isinstance(block, dict):
            continue
        content = str(block.get("content") or "").strip()
        if not content:
            continue
        block_type = str(block.get("type") or "").lower()
        if block_type == "image":
            lines.append(f"[Image: {content}]")
        else:
            lines.append(content)
    return "\n\n".join(lines)


def render_markdown(payload: dict[str, Any], document_type: str | None = None) -> str:
    """Render OCR pages as Markdown without document-family-specific filtering."""
    document, ocr_response = _unwrap_payload(payload)
    pages = ocr_response.get("pages", [])
    if not isinstance(pages, list) or not pages:
        raise ValueError("OCR JSON has no pages to convert")

    metadata = {
        "doc_id": document.get("doc_id"),
        "source_filename": document.get("source_filename"),
        "source_path": document.get("source_path"),
        "content_sha256": document.get("content_sha256"),
        "ocr_provider": document.get("ocr_provider"),
        "ocr_model": document.get("ocr_model"),
        "document_type": document_type or document.get("document_type"),
    }
    # JSON strings are valid quoted YAML scalars and safely retain punctuation.
    front_matter = ["---"]
    for key, value in metadata.items():
        if value not in (None, ""):
            front_matter.append(f"{key}: {json.dumps(str(value), ensure_ascii=False)}")
    front_matter.append("---")

    title = metadata["source_filename"] or document.get("doc_id") or "OCR document"
    sections = ["\n".join(front_matter), f"# {title}"]
    for position, page in enumerate(pages, start=1):
        if not isinstance(page, dict):
            continue
        page_index = page.get("index")
        page_number = page_index + 1 if isinstance(page_index, int) else position
        content = str(page.get("markdown") or "").strip()
        if not content:
            content = _block_text(page)
        sections.append(f"## Page {page_number}\n\n{content or '[No OCR text on this page.]'}")
    return "\n\n".join(sections).rstrip() + "\n"


def convert_file(
    source_path: Path,
    output_dir: Path,
    document_type: str | None = None,
) -> Path:
    with source_path.open("r", encoding="utf-8") as stream:
        payload = json.load(stream)
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object: {source_path}")

    document = payload.get("document", {})
    doc_id = document.get("doc_id") if isinstance(document, dict) else None
    output_path = output_dir / f"{doc_id or source_path.stem}.md"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render_markdown(payload, document_type), encoding="utf-8")
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert raw or wrapped Mistral OCR JSON to page-aware Markdown."
    )
    parser.add_argument("input", type=Path, help="OCR JSON file or a directory of JSON files")
    parser.add_argument("--output-dir", type=Path, default=Path("data/markdown/general"))
    parser.add_argument("--document-type", help="Optional family label, for example SMP or RCN")
    args = parser.parse_args()

    if args.input.is_file():
        input_files = [args.input]
    elif args.input.is_dir():
        input_files = sorted(args.input.rglob("*.json"))
    else:
        parser.error(f"Input does not exist: {args.input}")

    print(f"Found {len(input_files)} OCR JSON file(s).")
    failed = 0
    for position, source_path in enumerate(input_files, start=1):
        try:
            output_path = convert_file(source_path, args.output_dir, args.document_type)
            print(f"[{position}/{len(input_files)}] {source_path.name} -> {output_path}")
        except Exception as error:
            failed += 1
            print(f"FAILED: {source_path}: {error}")
    print(f"Completed: {len(input_files) - failed}; Failed: {failed}")


if __name__ == "__main__":
    main()
