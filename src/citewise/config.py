"""Central configuration. Every tunable lives here so experiments change one place."""

from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_dotenv() -> None:
    """Load KEY=VALUE lines from .env into the environment (without overriding)."""
    env_file = Path(os.environ.get("CITEWISE_ENV_FILE", REPO_ROOT / ".env"))
    if not env_file.exists():
        return
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


_load_dotenv()

# --- Storage -----------------------------------------------------------------
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://pcg:pcg@localhost:5432/citewise")
PAPERS_DIR = Path(os.environ.get("CITEWISE_PAPERS_DIR", REPO_ROOT / "papers"))
MANIFEST_PATH = PAPERS_DIR / "manifest.json"

# --- Embeddings (see docs/decisions/0003) -----------------------------------
EMBED_MODEL_NAME = "BAAI/bge-small-en-v1.5"
EMBED_MODEL_PATH = Path(
    os.environ.get("CITEWISE_EMBED_MODEL_PATH", REPO_ROOT / "models" / "bge-small-en-v1.5-onnx-Q")
)
EMBED_DIM = 384
EMBED_MAX_TOKENS = 512  # the model truncates anything longer, silently
EMBED_THREADS = int(os.environ["CITEWISE_EMBED_THREADS"]) if os.environ.get("CITEWISE_EMBED_THREADS") else None

# --- Chunking (see docs/decisions/0008) -------------------------------------
CHUNK_MAX_TOKENS = 350
CHUNK_OVERLAP_TOKENS = 60
