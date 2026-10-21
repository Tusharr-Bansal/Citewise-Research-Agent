"""Local text embeddings (docs/decisions/0003)."""

from __future__ import annotations

import hashlib
from functools import lru_cache
from typing import Callable

import numpy as np
from fastembed import TextEmbedding
from tokenizers import Tokenizer

from . import config

# bge models were trained with this instruction in front of short queries
# (not passages). Whether it helps on this corpus is measured, not assumed.
BGE_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "


@lru_cache(maxsize=1)
def _model() -> TextEmbedding:
    return TextEmbedding(
        model_name=config.EMBED_MODEL_NAME,
        specific_model_path=str(config.EMBED_MODEL_PATH),
        threads=config.EMBED_THREADS,  # 1 on small hosts: less memory, no CPU thrashing
    )


@lru_cache(maxsize=1)
def _tokenizer() -> Tokenizer:
    return Tokenizer.from_file(str(config.EMBED_MODEL_PATH / "tokenizer.json"))


def count_tokens(text: str) -> int:
    """Token count as the embedding model sees it (including [CLS]/[SEP])."""
    return len(_tokenizer().encode(text).ids)


def _cache_key(text: str) -> str:
    # The model name is part of the key, so switching models never reuses stale vectors.
    return hashlib.sha256(f"{config.EMBED_MODEL_NAME}\x00{text}".encode()).hexdigest()


# Small batches: ONNX Runtime keeps the peak activation memory of the largest batch it has seen.
# Measured in the app at 1 thread (decision 0015): batch 32 peaked at 634 MB, over Render's 512 MB,
# while batch 4 peaked at 309 MB and was faster per chunk (0.56 s vs 0.64 s; less padding).
EMBED_BATCH_SIZE = 4


def embed_passages(texts: list[str], batch_size: int = EMBED_BATCH_SIZE,
                   on_progress: Callable[[int, int], None] | None = None) -> np.ndarray:
    """Embed passages, reusing vectors cached on disk for text seen before.

    Embedding is deterministic for a fixed model, so a cache is safe, and it
    turns a 9-minute re-ingest into seconds when only cleaning rules change.
    """
    cache_file = config.REPO_ROOT / ".cache" / "passage_embeddings.npz"
    cache: dict[str, np.ndarray] = {}
    if cache_file.exists():
        with np.load(cache_file) as data:
            cache = {k: data[k] for k in data.files}

    keys = [_cache_key(t) for t in texts]
    missing = [i for i, k in enumerate(keys) if k not in cache]
    if missing:
        done = len(texts) - len(missing)
        if on_progress:
            on_progress(done, len(texts))
        # Embed in slices so progress can be reported between them (one slice ≈ a few seconds).
        step = batch_size * 2
        for s in range(0, len(missing), step):
            part = missing[s:s + step]
            for i, vec in zip(part, _model().embed([texts[i] for i in part], batch_size=batch_size)):
                cache[keys[i]] = np.asarray(vec, dtype=np.float32)
            done += len(part)
            if on_progress:
                on_progress(done, len(texts))
        cache_file.parent.mkdir(exist_ok=True)
        np.savez(cache_file, **cache)
    print(f"embeddings: {len(texts) - len(missing)} cached, {len(missing)} computed")
    return np.stack([cache[k] for k in keys])


def embed_query(text: str, use_prefix: bool = True) -> np.ndarray:
    q = (BGE_QUERY_PREFIX + text) if use_prefix else text
    return np.array(next(iter(_model().embed([q]))), dtype=np.float32)
