from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sqlite3
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import requests
from dotenv import load_dotenv


@dataclass(frozen=True)
class Document:
    source: str
    title: str
    file_path: str
    text: str
    content_hash: str


@dataclass(frozen=True)
class Chunk:
    strategy: str
    chunk_id: str
    section: str
    chunk_index: int
    text: str
    metadata: dict[str, str]


class Embedder:
    def __init__(self) -> None:
        load_dotenv()
        self._api_key = os.environ.get("OPENAI_API_KEY", "").strip()
        self._base_url = os.environ.get("OPENAI_API_BASE", "https://api.openai.com/v1").strip().rstrip("/")
        self._model = os.environ.get("EMBEDDING_MODEL", "text-embedding-3-small").strip()
        self._fallback_dim = 256
        self._fallback_used = False
        self._force_local = os.environ.get("RAG_EMBED_LOCAL", "").strip().lower() in (
            "1",
            "true",
            "yes",
            "on",
        )
        raw_timeout = os.environ.get("RAG_EMBED_TIMEOUT_SEC", "").strip()
        try:
            self._timeout_sec = max(5, int(raw_timeout)) if raw_timeout else 25
        except ValueError:
            self._timeout_sec = 25

    @property
    def model_name(self) -> str:
        if self._force_local or self._fallback_used or not self._api_key:
            return "hash-fallback-v1"
        return self._model

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        if self._force_local or self._fallback_used or not self._api_key:
            self._fallback_used = True
            return [self._hash_embedding(t, self._fallback_dim) for t in texts]
        url = f"{self._base_url}/embeddings"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        payload = {"model": self._model, "input": texts}
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=self._timeout_sec)
            resp.raise_for_status()
            data = resp.json()
            rows = data.get("data")
            if not isinstance(rows, list):
                raise RuntimeError("embeddings response.data is not a list")
            vectors: list[list[float]] = []
            for row in rows:
                emb = row.get("embedding") if isinstance(row, dict) else None
                if not isinstance(emb, list):
                    raise RuntimeError("embedding row malformed")
                vectors.append([float(x) for x in emb])
            if len(vectors) != len(texts):
                raise RuntimeError("embedding count mismatch")
            return vectors
        except Exception:
            self._fallback_used = True
            return [self._hash_embedding(t, self._fallback_dim) for t in texts]

    def embed_query(self, query: str) -> list[float]:
        return self.embed_texts([query])[0]

    @staticmethod
    def _hash_embedding(text: str, dim: int) -> list[float]:
        # Deterministic local fallback embedding (not semantic-quality, but stable for offline demos).
        out = [0.0] * dim
        words = re.findall(r"\w+", text.lower())
        if not words:
            return out
        for w in words:
            h = hashlib.sha256(w.encode("utf-8")).digest()
            idx = int.from_bytes(h[:4], "big") % dim
            sign = 1.0 if (h[4] % 2 == 0) else -1.0
            out[idx] += sign
        norm = math.sqrt(sum(v * v for v in out))
        if norm > 0:
            out = [v / norm for v in out]
        return out


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def load_document(path: Path) -> Document:
    ext = path.suffix.lower()
    if ext == ".pdf":
        text = _read_pdf(path)
        source = "pdf"
    elif ext == ".doc":
        text = _read_doc(path)
        source = "article"
    elif ext in {".md", ".markdown", ".rst", ".txt"}:
        text = path.read_text(encoding="utf-8", errors="ignore")
        source = "article"
    else:
        text = path.read_text(encoding="utf-8", errors="ignore")
        source = "code"
    content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return Document(
        source=source,
        title=path.name,
        file_path=str(path),
        text=text,
        content_hash=content_hash,
    )


def _read_pdf(path: Path) -> str:
    try:
        import pypdf  # type: ignore
    except Exception as e:
        raise RuntimeError(
            f"Для чтения PDF установите pypdf (pip install pypdf). Файл: {path}"
        ) from e
    reader = pypdf.PdfReader(str(path))
    pages: list[str] = []
    for p in reader.pages:
        pages.append(p.extract_text() or "")
    return "\n\n".join(pages)


def _read_doc(path: Path) -> str:
    """
    Converts legacy .doc to text using LibreOffice headless mode.
    """
    mode = os.environ.get("DOC_EXTRACTOR", "strings").strip().lower()
    if mode in ("strings", "fast"):
        return _read_doc_with_strings(path)

    with tempfile.TemporaryDirectory(prefix="doc2txt_") as tmp:
        outdir = Path(tmp)
        timeout_sec = 600
        raw_timeout = os.environ.get("DOC_CONVERT_TIMEOUT_SEC", "").strip()
        if raw_timeout:
            try:
                timeout_sec = max(60, int(raw_timeout))
            except ValueError:
                timeout_sec = 600
        # --convert-to txt:Text keeps plain text and works for .doc.
        cmd = [
            "libreoffice",
            "--headless",
            "--convert-to",
            "txt:Text",
            "--outdir",
            str(outdir),
            str(path),
        ]
        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=timeout_sec)
        except FileNotFoundError as e:
            return _read_doc_with_strings(path)
        except subprocess.CalledProcessError as e:
            _ = e
            return _read_doc_with_strings(path)
        except subprocess.TimeoutExpired as e:
            _ = e
            return _read_doc_with_strings(path)

        txt_path = outdir / f"{path.stem}.txt"
        if not txt_path.exists():
            # Fallback for some locales/variants where name might be transformed.
            cands = list(outdir.glob("*.txt"))
            if not cands:
                return _read_doc_with_strings(path)
            txt_path = cands[0]
        return txt_path.read_text(encoding="utf-8", errors="ignore")


def _read_doc_with_strings(path: Path) -> str:
    """
    Lightweight fallback for legacy .doc extraction when office converter is unavailable/hangs.
    """
    try:
        res = subprocess.run(
            ["strings", "-n", "4", str(path)],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except Exception as e:
        raise RuntimeError(
            "Не удалось извлечь текст из .doc ни через LibreOffice, ни через strings."
        ) from e
    text = res.stdout.strip()
    if not text:
        raise RuntimeError("Извлечение .doc через strings вернуло пустой текст.")
    return text


def chunk_fixed(text: str, *, chunk_size: int = 1200, overlap: int = 200) -> list[str]:
    t = text.strip()
    if not t:
        return []
    if overlap >= chunk_size:
        overlap = max(0, chunk_size // 4)
    step = max(1, chunk_size - overlap)
    chunks: list[str] = []
    i = 0
    while i < len(t):
        part = t[i : i + chunk_size].strip()
        if part:
            chunks.append(part)
        i += step
    return chunks


def chunk_by_structure(path: Path, text: str, *, chunk_size: int = 1200, overlap: int = 200) -> list[tuple[str, str]]:
    ext = path.suffix.lower()
    if ext in {".md", ".markdown", ".rst"}:
        return _chunk_markdown(text, chunk_size=chunk_size, overlap=overlap)
    if ext == ".py":
        return _chunk_python(text, chunk_size=chunk_size, overlap=overlap)
    fixed = chunk_fixed(text, chunk_size=chunk_size, overlap=overlap)
    return [(f"file:{path.name}", c) for c in fixed]


def _chunk_markdown(text: str, *, chunk_size: int, overlap: int) -> list[tuple[str, str]]:
    lines = text.splitlines()
    sections: list[tuple[str, list[str]]] = []
    cur_title = "root"
    cur_lines: list[str] = []
    for ln in lines:
        if re.match(r"^\s{0,3}#{1,6}\s+", ln):
            if cur_lines:
                sections.append((cur_title, cur_lines))
            cur_title = ln.strip("# ").strip() or "untitled"
            cur_lines = [ln]
        else:
            cur_lines.append(ln)
    if cur_lines:
        sections.append((cur_title, cur_lines))
    out: list[tuple[str, str]] = []
    for title, sec_lines in sections:
        sec_text = "\n".join(sec_lines).strip()
        if not sec_text:
            continue
        for part in chunk_fixed(sec_text, chunk_size=chunk_size, overlap=overlap):
            out.append((f"heading:{title}", part))
    return out


def _chunk_python(text: str, *, chunk_size: int, overlap: int) -> list[tuple[str, str]]:
    lines = text.splitlines()
    starts = [i for i, ln in enumerate(lines) if re.match(r"^(class|def)\s+\w+", ln)]
    if not starts:
        return [("module", c) for c in chunk_fixed(text, chunk_size=chunk_size, overlap=overlap)]
    starts.append(len(lines))
    out: list[tuple[str, str]] = []
    for i in range(len(starts) - 1):
        a, b = starts[i], starts[i + 1]
        block = "\n".join(lines[a:b]).strip()
        if not block:
            continue
        first = lines[a].strip() if a < len(lines) else "block"
        section = first.split(":", 1)[0]
        for part in chunk_fixed(block, chunk_size=chunk_size, overlap=overlap):
            out.append((section, part))
    return out


def make_chunks(doc: Document, strategy: str, *, chunk_size: int = 1200, overlap: int = 200) -> list[Chunk]:
    path = Path(doc.file_path)
    out: list[Chunk] = []
    if strategy == "fixed":
        parts = [(f"file:{path.name}", c) for c in chunk_fixed(doc.text, chunk_size=chunk_size, overlap=overlap)]
    elif strategy == "structured":
        parts = chunk_by_structure(path, doc.text, chunk_size=chunk_size, overlap=overlap)
    else:
        raise ValueError(f"Unknown strategy: {strategy}")
    for i, (section, text) in enumerate(parts):
        cid = f"{path.name}::{strategy}::{i:04d}"
        out.append(
            Chunk(
                strategy=strategy,
                chunk_id=cid,
                section=section,
                chunk_index=i,
                text=text,
                metadata={
                    "source": doc.source,
                    "title": doc.title,
                    "file": doc.file_path,
                    "section": section,
                    "chunk_id": cid,
                },
            )
        )
    return out


def open_db(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS documents (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          source TEXT NOT NULL,
          title TEXT NOT NULL,
          file_path TEXT NOT NULL,
          content_hash TEXT NOT NULL,
          total_chars INTEGER NOT NULL,
          created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS chunks (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
          strategy TEXT NOT NULL,
          chunk_id TEXT NOT NULL UNIQUE,
          section TEXT NOT NULL,
          chunk_index INTEGER NOT NULL,
          text TEXT NOT NULL,
          char_count INTEGER NOT NULL,
          token_estimate INTEGER NOT NULL,
          metadata_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS embeddings (
          chunk_row_id INTEGER PRIMARY KEY REFERENCES chunks(id) ON DELETE CASCADE,
          model TEXT NOT NULL,
          dim INTEGER NOT NULL,
          vector_json TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_chunks_strategy ON chunks(strategy);
        CREATE INDEX IF NOT EXISTS idx_chunks_doc ON chunks(document_id);
        CREATE INDEX IF NOT EXISTS idx_documents_path ON documents(file_path);
        """
    )
    conn.commit()


def reset_index(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        DELETE FROM embeddings;
        DELETE FROM chunks;
        DELETE FROM documents;
        """
    )
    conn.commit()


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if len(a) != len(b) or not a:
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na <= 0 or nb <= 0:
        return 0.0
    return dot / (math.sqrt(na) * math.sqrt(nb))


def iter_default_corpus(root: Path) -> Iterable[Path]:
    candidates = [
        "chat_service.py",
        "llm_agent.py",
        "api/main.py",
        "mcp_client.py",
        "app_settings.py",
        "sqlite_chat_storage.py",
        "frontend/src/App.tsx",
        "frontend/src/api.ts",
        "гэсэр.doc",
    ]
    seen: set[Path] = set()

    def _yield_if_file(p: Path) -> Iterable[Path]:
        rp = p.resolve()
        if rp in seen:
            return
        if p.exists() and p.is_file():
            seen.add(rp)
            yield p

    # Existing code-centric defaults.
    for rel in candidates:
        p = root / rel
        yield from _yield_if_file(p)

    # Project documentation (README if present).
    for pat in ("README*", "readme*"):
        for p in root.glob(pat):
            yield from _yield_if_file(p)

    # docs folder (articles, reports, control datasets, API/spec artifacts).
    docs_dir = root / "docs"
    if docs_dir.exists() and docs_dir.is_dir():
        for ext in ("*.md", "*.markdown", "*.rst", "*.txt", "*.json", "*.yaml", "*.yml"):
            for p in docs_dir.rglob(ext):
                yield from _yield_if_file(p)

    # Extra API/schema descriptors often stored outside docs.
    for ext in ("*.json", "*.yaml", "*.yml"):
        for p in (root / "api").glob(ext):
            yield from _yield_if_file(p)
