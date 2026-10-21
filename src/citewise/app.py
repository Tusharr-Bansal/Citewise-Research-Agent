"""Citewise web app: projects, PDF uploads, and cited answers (docs/decisions/0013, 0014).

Run locally:  uvicorn citewise.app:app --port 7860
"""

from __future__ import annotations

import json
import os
import queue
import re
import secrets
import tempfile
import threading
import time
from collections import defaultdict, deque
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from . import db
from .agent import ResearchAgent
from .ingest import DEMO_PROJECT_ID, IngestError, ingest_paper, new_paper_id
from .llm import LLM, DailyQuotaExhausted

STATIC = Path(__file__).with_name("static")
DEMO_DUMP = Path(os.environ.get("CITEWISE_DEMO_DUMP", Path(__file__).resolve().parents[2] / "deploy" / "demo_data.sql.gz"))
UPLOAD_DIR = Path(os.environ.get("CITEWISE_UPLOAD_DIR", tempfile.gettempdir())) / "citewise_uploads"

MAX_QUESTION_CHARS = 500
MAX_PDF_MB = 25
MAX_PAPERS_PER_PROJECT = 40
MAX_PROJECTS = int(os.environ.get("CITEWISE_MAX_PROJECTS", "300"))
PER_IP_PER_MINUTE = int(os.environ.get("CITEWISE_PER_IP_PER_MINUTE", "5"))
PER_IP_PER_DAY = int(os.environ.get("CITEWISE_PER_IP_PER_DAY", "30"))
# The answer model's free tier allows 500 requests/day; a question takes ~3 (up to 6), and each upload 1.
GLOBAL_PER_DAY = int(os.environ.get("CITEWISE_GLOBAL_PER_DAY", "120"))   # protects the free-tier API quota
PROJECTS_PER_IP_PER_DAY = 10
UPLOADS_PER_IP_PER_DAY = 120
_PROJECT_ID = re.compile(r"^[A-Za-z0-9_-]{6,64}$")

app = FastAPI(title="Citewise", docs_url=None, redoc_url=None)
_state: dict = {}
_answer_lock = threading.Lock()  # one agent run at a time: the free tier can't take parallel bursts


def state() -> dict:
    """Lazily create shared objects (so importing the module never touches the network/DB)."""
    if not _state:
        with db.connect() as conn:
            db.ensure_schema(conn)
            load_demo_if_missing(conn)
            # Uploads that were mid-flight when the server stopped will never finish: say so.
            conn.execute("UPDATE papers SET status = 'failed', error = 'Interrupted by a server restart. "
                         "Please upload it again.' WHERE status IN ('queued', 'processing')")
        _state.update(agent=ResearchAgent(), jobs=queue.Queue())
        threading.Thread(target=_ingest_worker, daemon=True).start()
    return _state


def load_demo_if_missing(conn) -> None:
    """First start against an empty database: load the demo project from the bundled data dump."""
    if conn.execute("SELECT 1 FROM projects WHERE id = %s", (DEMO_PROJECT_ID,)).fetchone():
        return
    dump = DEMO_DUMP
    if not dump.exists():
        return
    import gzip
    import subprocess
    sql = gzip.decompress(dump.read_bytes())
    subprocess.run(["psql", db.config.DATABASE_URL, "-q", "-v", "ON_ERROR_STOP=1"], input=sql, check=True,
                   stdout=subprocess.DEVNULL)


def _ingest_worker() -> None:
    """Processes uploads one at a time (embedding is CPU-bound; parallel jobs would just contend)."""
    conn, llm = db.connect(), LLM()
    while True:
        project_id, paper_id, path, filename = _state["jobs"].get()
        try:
            ingest_paper(conn, project_id, paper_id, path, filename, llm=llm)
        except IngestError:
            pass  # the paper row already carries the error message
        except Exception:  # noqa: BLE001
            conn.execute("UPDATE papers SET status = 'failed', error = 'Processing failed.' WHERE id = %s",
                         (paper_id,))
        finally:
            path.unlink(missing_ok=True)  # the PDF itself isn't kept after processing


# --- rate limiting -------------------------------------------------------------
class RateLimiter:
    """In-memory sliding windows. Resets on restart, which is acceptable for a demo."""

    def __init__(self) -> None:
        self.windows: dict[tuple, deque] = defaultdict(deque)
        self.lock = threading.Lock()

    def take(self, rules: list[tuple[tuple, int, int, str]], count: int = 1) -> None:
        """rules: (key, limit, window_seconds, message). All must allow `count` more; then all are charged."""
        now = time.time()
        with self.lock:
            for key, limit, span, msg in rules:
                q = self.windows[key]
                while q and now - q[0] > span:
                    q.popleft()
                if len(q) + count > limit:
                    raise HTTPException(status_code=429, detail=msg)
            for key, *_ in rules:
                self.windows[key].extend([now] * count)


limiter = RateLimiter()


def client_ip(request: Request) -> str:
    # Behind the hosting proxy, the first X-Forwarded-For entry is the visitor.
    fwd = request.headers.get("x-forwarded-for", "")
    return fwd.split(",")[0].strip() or (request.client.host if request.client else "unknown")


# --- helpers -------------------------------------------------------------------
def conn():
    """A short-lived connection per request. Sharing one connection across request threads
    would let one request's statements run inside another request's transaction."""
    state()
    return db.connect()


def get_project(project_id: str) -> dict:
    if not _PROJECT_ID.match(project_id):
        raise HTTPException(status_code=404, detail="Project not found.")
    with conn() as c:
        row = c.execute(
            "SELECT id, name, description, is_demo, created_at FROM projects WHERE id = %s", (project_id,)
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Project not found. Check the link, or the project may "
                                                    "have been deleted.")
    return {"id": row[0], "name": row[1], "description": row[2], "is_demo": row[3],
            "created_at": row[4].isoformat()}


def list_papers(project_id: str) -> list[dict]:
    with conn() as c:
        rows = c.execute(
            "SELECT id, title, authors, year, url, filename, n_pages, n_chunks, status, error "
            "FROM papers WHERE project_id = %s ORDER BY created_at, id", (project_id,)
        ).fetchall()
    keys = ("id", "title", "authors", "year", "url", "filename", "n_pages", "n_chunks", "status", "error")
    return [dict(zip(keys, r)) for r in rows]


# --- pages -----------------------------------------------------------------------
@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/api/ping")
def ping() -> dict:
    """Keep-alive endpoint for uptime monitors. Deliberately touches nothing: pinging the
    database every few minutes would keep the free Neon compute awake and spend its
    monthly compute allowance (docs/decisions/0015)."""
    return {"ok": True}


@app.get("/api/health")
def health() -> dict:
    with conn() as c:
        return {"status": "ok",
                "projects": c.execute("SELECT count(*) FROM projects").fetchone()[0],
                "demo_chunks": c.execute("SELECT count(*) FROM chunks WHERE project_id = %s",
                                         (DEMO_PROJECT_ID,)).fetchone()[0]}


@app.get("/api/eval")
def eval_summary() -> JSONResponse:
    """Measured results on the demo project, written by eval/publish_summary.py."""
    f = STATIC / "eval_summary.json"
    if not f.exists():
        raise HTTPException(status_code=404, detail="No evaluation published yet.")
    return JSONResponse(json.loads(f.read_text()))


# --- projects --------------------------------------------------------------------
class NewProject(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=400)


@app.post("/api/projects")
def create_project(body: NewProject, request: Request) -> dict:
    ip = client_ip(request)
    limiter.take([(("project", ip), PROJECTS_PER_IP_PER_DAY, 86400,
                   "You've created the maximum number of projects for today.")])
    with conn() as c:
        if c.execute("SELECT count(*) FROM projects").fetchone()[0] >= MAX_PROJECTS:
            raise HTTPException(status_code=503, detail="The demo server is full. Please try again later.")
        pid = secrets.token_urlsafe(12)  # ~96 random bits: the link is the key (docs/decisions/0014)
        c.execute("INSERT INTO projects (id, name, description) VALUES (%s, %s, %s)",
                  (pid, " ".join(body.name.split()), body.description.strip()))
    return get_project(pid)


@app.get("/api/projects/{project_id}")
def project_detail(project_id: str) -> dict:
    return {**get_project(project_id), "papers": list_papers(project_id)}


@app.post("/api/projects/{project_id}/papers")
async def upload(project_id: str, request: Request, files: list[UploadFile] = File(...)) -> dict:
    project = get_project(project_id)
    if project["is_demo"]:
        raise HTTPException(status_code=403, detail="The demo project is read-only. Create your own project to upload papers.")
    with conn() as c:
        existing = c.execute("SELECT count(*) FROM papers WHERE project_id = %s", (project_id,)).fetchone()[0]
    if existing + len(files) > MAX_PAPERS_PER_PROJECT:
        raise HTTPException(status_code=400, detail=f"A project can hold up to {MAX_PAPERS_PER_PROJECT} papers.")
    ip = client_ip(request)
    limiter.take([(("upload", ip), UPLOADS_PER_IP_PER_DAY, 86400,
                   "Daily upload limit reached. Please try again tomorrow.")], count=len(files))
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    accepted, rejected = [], []
    for f in files:
        name = Path(f.filename or "paper.pdf").name[:120]
        data = await f.read(MAX_PDF_MB * 1024 * 1024 + 1)
        if len(data) > MAX_PDF_MB * 1024 * 1024:
            rejected.append({"filename": name, "error": f"Larger than {MAX_PDF_MB} MB."})
            continue
        if not data.startswith(b"%PDF"):
            rejected.append({"filename": name, "error": "Not a PDF file."})
            continue
        paper_id = new_paper_id(Path(name).stem)
        path = UPLOAD_DIR / f"{paper_id}.pdf"
        path.write_bytes(data)
        with conn() as c:
            c.execute("INSERT INTO papers (id, project_id, title, filename, status) VALUES (%s, %s, %s, %s, 'queued')",
                      (paper_id, project_id, Path(name).stem, name))
        state()["jobs"].put((project_id, paper_id, path, name))
        accepted.append(paper_id)
    return {"accepted": accepted, "rejected": rejected, "papers": list_papers(project_id)}


@app.delete("/api/projects/{project_id}/papers/{paper_id}")
def delete_paper(project_id: str, paper_id: str) -> dict:
    project = get_project(project_id)
    if project["is_demo"]:
        raise HTTPException(status_code=403, detail="The demo project is read-only.")
    with conn() as c:
        status = c.execute("SELECT status FROM papers WHERE id = %s AND project_id = %s",
                           (paper_id, project_id)).fetchone()
        if status is None:
            raise HTTPException(status_code=404, detail="Paper not found.")
        if status[0] in ("queued", "processing"):
            raise HTTPException(status_code=409, detail="Wait until this paper finishes processing.")
        with c.transaction():
            c.execute("DELETE FROM papers WHERE id = %s", (paper_id,))  # chunks cascade
            c.execute("UPDATE projects SET updated_at = now() WHERE id = %s", (project_id,))
    return {"papers": list_papers(project_id)}


# --- questions --------------------------------------------------------------------
class Ask(BaseModel):
    question: str = Field(min_length=3, max_length=MAX_QUESTION_CHARS)


@app.post("/api/projects/{project_id}/ask")
def ask(project_id: str, body: Ask, request: Request) -> JSONResponse:
    get_project(project_id)
    question = " ".join(body.question.split())
    ip = client_ip(request)
    limiter.take([
        (("ask-global",), GLOBAL_PER_DAY, 86400, "The demo has reached its daily question limit. Please try again tomorrow."),
        (("ask-day", ip), PER_IP_PER_DAY, 86400, "You've reached today's question limit. Please try again tomorrow."),
        (("ask-min", ip), PER_IP_PER_MINUTE, 60, "Too many questions in a minute. Wait a moment and try again."),
    ])
    try:
        with _answer_lock:
            r = state()["agent"].run(project_id, question)
    except DailyQuotaExhausted:
        raise HTTPException(status_code=429, detail="Today's free AI quota is used up. It resets at midnight "
                                                    "Pacific time; please try again after that.")
    except Exception as e:  # noqa: BLE001
        if getattr(e, "code", None) in (429, 503):
            raise HTTPException(status_code=503, detail="The language model is busy right now. Please try again in a minute.")
        raise HTTPException(status_code=500, detail="Something went wrong while answering. Please try again.")
    cited = set(r.cited)
    return JSONResponse({
        "question": r.question,
        "answer": r.answer,
        "answerable": r.answerable,
        "sources": [
            {"label": s.label, "cited": s.label in cited, "title": s.title, "authors": s.authors,
             "year": s.year, "url": s.url, "paper_id": s.hit.paper_key,
             "pages": [s.hit.page_start, s.hit.page_end], "text": s.hit.text}
            for s in r.sources
        ],
        "invalid_citations": r.invalid_citations,
        "trace": [
            {k: t[k] for k in ("step", "round", "query", "paper", "new") if k in t}
            | ({"output": t["output"]} if t["step"] == "check" else {})
            for t in r.trace
        ],
        "stats": {"llm_calls": r.llm_calls, "input_tokens": r.input_tokens,
                  "output_tokens": r.output_tokens, "latency_s": r.latency_s},
    })
