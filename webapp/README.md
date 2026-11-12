# BOXGPT web demo

The web demo lives in this directory and calls the existing Postgres corpus through a small API adapter. It does not modify the OCR, ingestion, or chunk-generation pipeline.

## What is included

- Public BOXGPT landing page, demo login, and responsive Bootstrap/JavaScript workspace.
- Ask, Documents, and admin-only Analytics views.
- Streamed OpenAI answer with source buttons; the source panel opens a PDF inline when the original is available.
- Four-account support using pre-created `admin` and `user` accounts. Passwords are PBKDF2-hashed; sessions are opaque, database-backed, and stored in HttpOnly cookies.
- Question history stores the signed-in user's question, generated answer, cited source metadata, response duration, and answer-review feedback in Postgres. Users see their own history; admins can review workspace history. Treat this as demo data and do not enter confidential information without an approved retention policy.
- BGE-M3 is loaded once when the API starts and reused for each question. Run one API worker on an 8 GB demo instance to avoid loading extra model copies.

## Local run

From the repository root:

```bash
.venv/bin/python -m pip install -r requirements-web.txt
cp .env.web.example .env.web
```

Edit `.env.web` and set `OPENAI_API_KEY`, `OPENAI_MODEL`, and (for EC2) `DATABASE_URL`. Keep `.env.web` private; the OpenAI key is used only by the Python API and is never sent to the browser. Local development can omit `DATABASE_URL` and use `config.json`.

Load the settings into the current terminal and create the demo accounts. Use distinct passwords; the prompts do not echo passwords or put them in shell history.

```bash
set -a
source .env.web
set +a
.venv/bin/python -m webapp.api.seed_user demo-admin-1 --role admin
.venv/bin/python -m webapp.api.seed_user demo-admin-2 --role admin
.venv/bin/python -m webapp.api.seed_user demo-user-1 --role user
.venv/bin/python -m webapp.api.seed_user demo-user-2 --role user
```

Start the web server with a single worker. BGE-M3 loads at startup; wait for that startup to finish before opening the site.

```bash
.venv/bin/uvicorn webapp.api.app:app --host 127.0.0.1 --port 8000 --workers 1
```

Open `http://127.0.0.1:8000`. The account usernames above are examples; choose your own before sharing the demo.

## EC2 notes

- Use `DATABASE_URL` and `OPENAI_API_KEY` as server environment secrets. Do not copy the local `config.json` or commit secrets.
- Set `COOKIE_SECURE=true` when serving over HTTPS behind a reverse proxy. Keep the database port private; expose only the proxy/web port.
- Configure `PDF_ROOT` to a directory that contains the original PDFs. The viewer looks for an original filename recorded in document metadata, or a matching filename/title. No download button is provided. If source names differ, add an explicit document-to-PDF mapping before the final demo.
- This is a demonstration scaffold, not a hardened public authentication system. Add TLS, rate limiting, password reset/rotation, backups, and operational monitoring before broader use.

## Timing behavior

Each question first gets embedded and searched; only after the relevant passages arrive can the OpenAI answer stream start. The browser renders answer text as OpenAI sends it. This lowers perceived wait time but does not make retrieval or generation itself instantaneous. The API records aggregate duration so later optimization can distinguish a slow search from a slow answer provider.

## Hybrid retrieval tuning

The web API combines BGE-M3 vector results and PostgreSQL lexical results with Reciprocal Rank Fusion, reserves the strongest lexical result, and uses Rajiv's MMR implementation to diversify the remaining source slots. The defaults in `.env.web.example` slightly boost lexical evidence while preserving semantic retrieval for fuzzy questions. `RAG_LEXICAL_RESERVED_SLOTS=1` prevents an exact name or document-number match from being discarded by the vector-only MMR score. Change one setting at a time and validate both exact and fuzzy questions before deployment.

Lexical retrieval uses relaxed OR matching followed by query-term coverage reranking, so a typo or one missing word does not eliminate all lexical candidates. After hybrid selection, the API expands around the strongest results using document `chunk_index`, removes duplicate chunks, and applies `RAG_MAX_CONTEXT_CHUNKS` as a hard context-count cap. Neighbor expansion is deliberately limited to the top results because extra chunks increase OpenAI input tokens. `RAG_CONTEXT_TOKEN_BUDGET` then shares an approximate context budget across the selected excerpts; the default is 2,000 tokens.

## Question history and answer review

Question events are stored in the `web_question_events` table, including question text, answer text, source references, signed-in account, and optional `accurate` / `needs_review` feedback. Existing aggregate-only rows are preserved but cannot be reconstructed into question history. Users can revisit their own recent questions; admins can review workspace questions in Analytics. The feedback is a human assessment, not an automatic correctness score.
