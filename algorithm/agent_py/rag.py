from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .config import KB_DIR
from .models import KnowledgeRef


@dataclass
class Chunk:
    doc_id: str
    title: str
    chunk_id: str
    text: str


STOP_TERMS = {"这个", "那个", "什么", "怎么", "如何", "是否", "还是", "一下", "请问"}


class KeywordRAG:
    def __init__(self, kb_dir: str | Path = KB_DIR) -> None:
        self.kb_dir = Path(kb_dir)
        self.chunks = self._load_chunks()

    def reload(self) -> None:
        self.chunks = self._load_chunks()

    def _load_chunks(self) -> list[Chunk]:
        if not self.kb_dir.exists():
            return []
        chunks: list[Chunk] = []
        for path in sorted(self.kb_dir.glob("**/*")):
            if path.suffix.lower() not in {".md", ".txt"} or not path.is_file():
                continue
            text = path.read_text(encoding="utf-8").strip()
            if not text:
                continue
            doc_id = path.stem
            sections = self._split_markdown(text)
            for index, (title, body) in enumerate(sections, start=1):
                chunks.append(Chunk(doc_id, title or doc_id, f"{doc_id}-{index}", body))
        return chunks

    def _split_markdown(self, text: str) -> list[tuple[str, str]]:
        lines = text.splitlines()
        sections: list[tuple[str, list[str]]] = []
        current_title = ""
        current: list[str] = []
        for line in lines:
            if line.startswith("#"):
                if current or current_title:
                    sections.append((current_title, current))
                current_title = line.lstrip("#").strip()
                current = []
            else:
                current.append(line)
        if current or current_title:
            sections.append((current_title, current))
        if not sections:
            return [("", text)]
        return [(title, "\n".join(body).strip() or title) for title, body in sections]

    def search(self, query: str, context_terms: list[str] | None = None, top_k: int = 3) -> list[KnowledgeRef]:
        terms = self._terms(query)
        for term in context_terms or []:
            terms.extend(self._terms(term))
        if not terms:
            return []

        scored: list[tuple[int, Chunk]] = []
        for chunk in self.chunks:
            haystack = f"{chunk.title}\n{chunk.text}".lower()
            score = 0
            for term in terms:
                if term in haystack:
                    score += 3 if term in chunk.title.lower() else 1
            if score > 0:
                scored.append((score, chunk))

        scored.sort(key=lambda item: item[0], reverse=True)
        refs: list[KnowledgeRef] = []
        seen = set()
        for _, chunk in scored:
            if chunk.chunk_id in seen:
                continue
            seen.add(chunk.chunk_id)
            refs.append(
                KnowledgeRef(
                    doc_id=chunk.doc_id,
                    title=chunk.title,
                    chunk_id=chunk.chunk_id,
                    snippet=self._snippet(chunk.text),
                )
            )
            if len(refs) >= top_k:
                break
        return refs

    def _terms(self, text: str) -> list[str]:
        lowered = text.lower()
        terms = [term for term in re.findall(r"[a-z0-9_]+", lowered) if len(term) >= 2]
        chinese_runs = re.findall(r"[\u4e00-\u9fff]{2,}", lowered)
        for run in chinese_runs:
            clean = run
            for stop in STOP_TERMS:
                clean = clean.replace(stop, "")
            if len(clean) >= 2:
                terms.append(clean)
            for size in (2, 3):
                terms.extend(clean[index : index + size] for index in range(max(0, len(clean) - size + 1)))
        return [term for term in terms if len(term) >= 2 and term not in STOP_TERMS]

    def _snippet(self, text: str, limit: int = 90) -> str:
        compact = re.sub(r"\s+", " ", text).strip()
        if len(compact) <= limit:
            return compact
        return compact[: limit - 1] + "…"
