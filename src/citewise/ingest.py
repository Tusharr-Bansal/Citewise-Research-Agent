"""Turn uploaded PDFs into searchable chunks inside a project.

Two entry points:
- `ingest_paper(...)`: one PDF into one project. Used by the web app's upload worker.
- `python -m citewise.ingest demo`: (re)build the built-in demo project from
  papers/manifest.json, keeping its paper and chunk ids stable so the evaluation
  gold set (which refers to chunk ids) stays valid.
"""

from __future__ import annotations

import json
import re
import secrets
import sys
import time
from pathlib import Path

import psycopg

from . import config, db
from .chunking import chunk_paper
from .embeddings import count_tokens, embed_passages
from .pdf_extract import extract

DEMO_PROJECT_ID = "demo-mysteth"
DEMO_NAME = "MySteth 2.0 literature review"
DEMO_DESCRIPTION = (
    "Pediatric heart-sound (phonocardiogram) screening: murmur detection, signal quality "
    "assessment, self-supervised audio models, uncertainty estimation and calibration."
)
MIN_TEXT_CHARS = 1500  # below this, the PDF is almost certainly scanned images

META_PROMPT = """Below is the first page of a research paper, extracted from a PDF.
Return its bibliographic details.
- title: the paper's full title.
- authors: first author's surname followed by "et al." if there are several authors (e.g. "Guo et al."), or the surnames if two.
- year: the publication year as an integer, or null if it isn't stated.

First page:
\"\"\"{text}\"\"\"
"""
META_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "authors": {"type": "string"},
        "year": {"type": ["integer", "null"]},
    },
    "required": ["title", "authors", "year"],
}
_DOI = re.compile(r"\b(10\.\d{4,9}/[^\s\"<>]+[^\s\"<>.,;)\]])")
_ARXIV = re.compile(r"arXiv:(\d{4}\.\d{4,5})")


class IngestError(Exception):
    """A problem with the PDF itself, explained in words the uploader understands."""


def find_link(text: str) -> str | None:
    if m := _ARXIV.search(text):
        return f"https://arxiv.org/abs/{m.group(1)}"
    if m := _DOI.search(text):
        return f"https://doi.org/{m.group(1)}"
    return None


def slug(text: str, n: int = 32) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    return s[:n].rstrip("_") or "paper"


def new_paper_id(title: str) -> str:
    """Readable and unique: a short slug plus random hex (ids are global across projects)."""
    return f"{slug(title, 28)}_{secrets.token_hex(3)}"


def extract_metadata(first_page: str, filename: str, llm) -> dict:
    fallback = {"title": Path(filename).stem.replace("_", " "), "authors": "", "year": None}
    if llm is None:
        return fallback
    try:
        meta = llm.generate(META_PROMPT.format(text=first_page[:4000]), json_schema=META_SCHEMA,
                            purpose="ingest_metadata").json()
    except Exception:  # noqa: BLE001 - metadata is nice-to-have; never fail an upload over it
        return fallback
    title = " ".join(str(meta.get("title") or "").split())
    year = meta.get("year")
    return {
        "title": title or fallback["title"],
        "authors": " ".join(str(meta.get("authors") or "").split()),
        "year": year if isinstance(year, int) and 1900 <= year <= 2100 else None,
    }


def ingest_paper(conn: psycopg.Connection, project_id: str, paper_id: str, pdf_path: Path,
                 filename: str, llm=None, meta: dict | None = None) -> int:
    """Extract, chunk, embed and store one PDF. The paper row must already exist.

    Updates the paper's status as it goes. Returns the number of chunks stored.
    """
    conn.execute("UPDATE papers SET status = 'processing', error = NULL WHERE id = %s", (paper_id,))
    try:
        pages = extract(pdf_path)
        text_chars = sum(len(p.text.strip()) for p in pages)
        if text_chars < MIN_TEXT_CHARS:
            raise IngestError("No selectable text found. This looks like a scanned PDF; "
                              "upload a version with real text.")
        if meta is None:
            meta = extract_metadata(pages[0].text, filename, llm)
            meta["url"] = find_link(pages[0].text + "\n" + (pages[1].text if len(pages) > 1 else ""))
        chunks = chunk_paper(paper_id, pages, count_tokens, config.CHUNK_MAX_TOKENS,
                             config.CHUNK_OVERLAP_TOKENS)
        if not chunks:
            raise IngestError("The PDF has no usable text after cleaning.")
        vectors = embed_passages([c.text for c in chunks])
        with conn.transaction():
            conn.execute("DELETE FROM chunks WHERE paper_id = %s", (paper_id,))
            with conn.cursor() as cur:
                cur.executemany(
                    "INSERT INTO chunks (id, project_id, paper_id, chunk_index, page_start, page_end, "
                    "n_tokens, text, embedding) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    [(c.chunk_id, project_id, paper_id, c.index, c.page_start, c.page_end, c.n_tokens,
                      c.text, v) for c, v in zip(chunks, vectors)],
                )
            conn.execute(
                "UPDATE papers SET status = 'ready', title = %s, authors = %s, year = %s, url = %s, "
                "n_pages = %s, n_chunks = %s WHERE id = %s",
                (meta["title"], meta.get("authors", ""), meta.get("year"), meta.get("url"),
                 len(pages), len(chunks), paper_id),
            )
            conn.execute("UPDATE projects SET updated_at = now() WHERE id = %s", (project_id,))
        return len(chunks)
    except IngestError as e:
        conn.execute("UPDATE papers SET status = 'failed', error = %s WHERE id = %s", (str(e), paper_id))
        raise
    except Exception as e:  # noqa: BLE001
        conn.execute("UPDATE papers SET status = 'failed', error = %s WHERE id = %s",
                     ("This PDF couldn't be processed.", paper_id))
        raise IngestError("This PDF couldn't be processed.") from e


def build_demo() -> None:
    """(Re)build the read-only demo project from papers/manifest.json."""
    t0 = time.perf_counter()
    manifest = json.loads(config.MANIFEST_PATH.read_text())
    conn = db.connect()
    db.ensure_schema(conn)
    conn.execute("DELETE FROM projects WHERE id = %s", (DEMO_PROJECT_ID,))  # cascades to papers/chunks
    conn.execute("INSERT INTO projects (id, name, description, is_demo) VALUES (%s, %s, %s, true)",
                 (DEMO_PROJECT_ID, DEMO_NAME, DEMO_DESCRIPTION))
    total = 0
    for e in manifest:
        conn.execute(
            "INSERT INTO papers (id, project_id, title, authors, year, url, filename, status) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, 'queued')",
            (e["key"], DEMO_PROJECT_ID, e["title"], e["authors"], e["year"], e["url"], f"{e['key']}.pdf"),
        )
        n = ingest_paper(conn, DEMO_PROJECT_ID, e["key"], config.PAPERS_DIR / f"{e['key']}.pdf",
                         f"{e['key']}.pdf", meta={k: e[k] for k in ("title", "authors", "year", "url")})
        total += n
        print(f"{e['key']}: {n} chunks")
    print(f"\ndemo project: {len(manifest)} papers, {total} chunks in {time.perf_counter() - t0:.0f}s")


if __name__ == "__main__":
    if sys.argv[1:] != ["demo"]:
        sys.exit("usage: python -m citewise.ingest demo")
    build_demo()
