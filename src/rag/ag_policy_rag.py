from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple, Union

import faiss  # type: ignore
import numpy as np
import yaml
from openai import OpenAI
from pypdf import PdfReader

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


# -----------------------------
# Conflict-prevention “persona”
# -----------------------------
AGRICULTURAL_POLICY_SYSTEM_PROMPT = """\
You are an AI Agricultural Policy Assistant with a conflict-prevention lens.
You help users design agricultural policies that reduce drivers of violent conflict.

Rules:
- Ground your answer in the provided SDG time-series summaries and Pathways for Peace excerpts.
- If evidence is missing, say so and propose what to collect.
- Be explicit about distributional impacts (who benefits/loses), grievance risks, and inclusion.
- Provide practical options (near-term, medium-term, structural) plus risk mitigations.
- Do not fabricate citations; refer to the provided excerpts by page when relevant.
"""


# -----------------------------
# Data structures
# -----------------------------
@dataclass(frozen=True)
class IndicatorSpec:
    sdg_indicator: str           # e.g. "2.1.1"
    series_code: str             # e.g. "SN_ITK_DEFC"
    name: str
    tags: List[str] = field(default_factory=list)


@dataclass
class RetrievedChunk:
    text: str
    page: int
    score: float


# -----------------------------
# Catalog loading
# -----------------------------
def load_indicator_catalog(yaml_path: Union[str, Path]) -> List[IndicatorSpec]:
    p = Path(yaml_path)
    items = yaml.safe_load(p.read_text(encoding="utf-8"))
    out: List[IndicatorSpec] = []
    for it in items or []:
        out.append(
            IndicatorSpec(
                sdg_indicator=str(it["sdg_indicator"]).strip(),
                series_code=str(it["series_code"]).strip(),
                name=str(it["name"]).strip(),
                tags=[str(t).strip() for t in (it.get("tags") or [])],
            )
        )
    return out


# -----------------------------
# Simple matching helpers
# -----------------------------
_WORD = re.compile(r"[a-z0-9]+")


def _tokens(s: str) -> set[str]:
    return set(_WORD.findall(s.lower()))


def match_indicators_in_query(
    query: str,
    catalog: Sequence[IndicatorSpec],
    max_matches: int = 3,
) -> List[IndicatorSpec]:
    q = query.lower()

    # hard matches (explicit SDG code or series code)
    hard: List[Tuple[int, IndicatorSpec]] = []
    for spec in catalog:
        if spec.sdg_indicator.lower() in q:
            hard.append((100, spec))
        elif spec.series_code.lower() in q:
            hard.append((95, spec))

    if hard:
        hard_sorted = sorted(hard, key=lambda x: x[0], reverse=True)
        return [s for _, s in hard_sorted[:max_matches]]

    # soft matches by token overlap
    qt = _tokens(query)
    scored: List[Tuple[float, IndicatorSpec]] = []
    for spec in catalog:
        text = f"{spec.sdg_indicator} {spec.series_code} {spec.name} {' '.join(spec.tags)}"
        st = _tokens(text)
        overlap = len(qt & st)
        denom = max(8, len(st))
        score = overlap / denom
        if score > 0:
            scored.append((score, spec))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [s for _, s in scored[:max_matches]]


def match_areas_in_query(
    query: str,
    area_catalog: Sequence[str],
    max_matches: int = 3,
) -> List[str]:
    q = query.lower()
    hits = []
    for a in area_catalog:
        al = a.lower()
        # prefer whole-word-ish matches
        if al in q:
            hits.append(a)

    if hits:
        # keep order but unique
        out = []
        for h in hits:
            if h not in out:
                out.append(h)
        return out[:max_matches]

    # fallback: token overlap
    qt = _tokens(query)
    scored: List[Tuple[float, str]] = []
    for a in area_catalog:
        at = _tokens(a)
        overlap = len(qt & at)
        if overlap:
            scored.append((overlap / max(3, len(at)), a))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [a for _, a in scored[:max_matches]]


# -----------------------------
# Embeddings + FAISS index
# -----------------------------
class OpenAIEmbedder:
    """
    Batches embedding calls to respect OpenAI embeddings limits:
    - 8192 tokens per input
    - 2048 inputs per request
    - 300,000 tokens summed across all inputs per request
    """
    def __init__(
        self,
        client: OpenAI | None = None,
        model: str = "text-embedding-3-small",
        max_total_tokens_per_request: int = 250_000,  # safety margin under 300k
        max_inputs_per_request: int = 2048,
        max_tokens_per_input: int = 8192,
        encoding_name: str = "cl100k_base",
    ):
        self.client = client or OpenAI()
        self.model = model
        self.max_total_tokens_per_request = max_total_tokens_per_request
        self.max_inputs_per_request = max_inputs_per_request
        self.max_tokens_per_input = max_tokens_per_input

        # Optional exact token counting; fallback to rough estimate if not installed
        try:
            import tiktoken  # type: ignore
            self._enc = tiktoken.get_encoding(encoding_name)
        except Exception:
            self._enc = None

    def _count_tokens(self, text: str) -> int:
        if self._enc is None:
            # rough heuristic ~4 chars/token
            return max(1, len(text) // 4)
        return len(self._enc.encode(text))

    def _truncate_to_max_input(self, text: str) -> str:
        # If we have tiktoken, truncate by tokens; otherwise truncate by chars.
        if self._enc is None:
            approx_max_chars = self.max_tokens_per_input * 4
            return text[:approx_max_chars]
        toks = self._enc.encode(text)
        toks = toks[: self.max_tokens_per_input]
        return self._enc.decode(toks)

    def embed(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, 0), dtype="float32")

        # Prepare + truncate long items (rare for your PDF chunks, but safe)
        cleaned: list[str] = [self._truncate_to_max_input(t) for t in texts]

        # Build batches respecting BOTH total tokens and max items
        batches: list[list[str]] = []
        cur: list[str] = []
        cur_tokens = 0

        for t in cleaned:
            t_tokens = self._count_tokens(t)

            would_exceed_tokens = cur and (cur_tokens + t_tokens > self.max_total_tokens_per_request)
            would_exceed_items = cur and (len(cur) >= self.max_inputs_per_request)

            if would_exceed_tokens or would_exceed_items:
                batches.append(cur)
                cur = [t]
                cur_tokens = t_tokens
            else:
                cur.append(t)
                cur_tokens += t_tokens

        if cur:
            batches.append(cur)

        # Call embeddings endpoint per batch and concatenate results
        vecs: list[np.ndarray] = []
        for batch in batches:
            resp = self.client.embeddings.create(model=self.model, input=batch)
            # Response order matches input order by index
            for d in resp.data:
                vecs.append(np.array(d.embedding, dtype="float32"))

        return np.vstack(vecs)


class PathwaysIndex:
    def __init__(
        self,
        pdf_path: Union[str, Path],
        index_dir: Union[str, Path] = "rag_store",
        embedder: Optional[OpenAIEmbedder] = None,
        chunk_chars: int = 1400,
        chunk_overlap: int = 200,
    ) -> None:
        self.pdf_path = Path(pdf_path)
        self.index_dir = Path(index_dir)
        self.embedder = embedder or OpenAIEmbedder()
        self.chunk_chars = chunk_chars
        self.chunk_overlap = chunk_overlap

        self.index_path = self.index_dir / "pathways_faiss.index"
        self.meta_path = self.index_dir / "pathways_chunks.jsonl"

        self._index: Optional[faiss.Index] = None
        self._chunks: List[Dict[str, Any]] = []

    def ensure_index(self, rebuild: bool = False) -> None:
        self.index_dir.mkdir(parents=True, exist_ok=True)

        if not rebuild and self.index_path.exists() and self.meta_path.exists():
            self._index = faiss.read_index(str(self.index_path))
            self._chunks = [json.loads(l) for l in self.meta_path.read_text(encoding="utf-8").splitlines() if l.strip()]
            return

        chunks = self._chunk_pdf()
        texts = [c["text"] for c in chunks]
        emb = self.embedder.embed(texts)
        faiss.normalize_L2(emb)

        index = faiss.IndexFlatIP(emb.shape[1])
        index.add(emb)

        faiss.write_index(index, str(self.index_path))
        self.meta_path.write_text("\n".join(json.dumps(c, ensure_ascii=False) for c in chunks), encoding="utf-8")

        self._index = index
        self._chunks = chunks

    def retrieve(self, query: str, k: int = 5) -> List[RetrievedChunk]:
        if self._index is None or not self._chunks:
            raise RuntimeError("Index not loaded. Call ensure_index() first.")

        q = self.embedder.embed([query])
        faiss.normalize_L2(q)
        scores, idxs = self._index.search(q, k)

        out: List[RetrievedChunk] = []
        for score, idx in zip(scores[0], idxs[0]):
            if idx < 0 or idx >= len(self._chunks):
                continue
            c = self._chunks[int(idx)]
            out.append(RetrievedChunk(text=c["text"], page=int(c["page"]), score=float(score)))
        return out

    def _chunk_pdf(self) -> List[Dict[str, Any]]:
        if not self.pdf_path.exists():
            raise FileNotFoundError(f"Missing PDF: {self.pdf_path}")

        reader = PdfReader(str(self.pdf_path))
        chunks: List[Dict[str, Any]] = []

        for i, page in enumerate(reader.pages, start=1):
            text = (page.extract_text() or "").strip()
            if not text:
                continue

            # normalize whitespace
            text = re.sub(r"\s+", " ", text)

            start = 0
            while start < len(text):
                end = min(len(text), start + self.chunk_chars)
                chunk_text = text[start:end].strip()
                if chunk_text:
                    chunks.append({"page": i, "text": chunk_text})
                if end >= len(text):
                    break
                start = max(0, end - self.chunk_overlap)

        return chunks


# -----------------------------
# Main assistant
# -----------------------------
class AgriculturalPolicyRAGAssistant:
    def __init__(
        self,
        pathways_index: PathwaysIndex,
        indicator_catalog: Sequence[IndicatorSpec],
        area_catalog: Sequence[str],
        fao_data_fetcher: Optional[Callable[[str, str], Dict[int, float]]] = None,
        client: Optional[OpenAI] = None,
        model: str = "gpt-4.1-mini",
    ) -> None:
        self.pathways_index = pathways_index
        self.indicator_catalog = list(indicator_catalog)
        self.area_catalog = list(area_catalog)
        self.fao_data_fetcher = fao_data_fetcher
        self.client = client or OpenAI()
        self.model = model

        self._indicator_by_sdg: Dict[str, IndicatorSpec] = {s.sdg_indicator: s for s in self.indicator_catalog}
        self._indicator_by_series: Dict[str, IndicatorSpec] = {s.series_code: s for s in self.indicator_catalog}

    def answer_question(
        self,
        question: str,
        explicit_sdg_indicators: Optional[Sequence[str]] = None,
        explicit_areas: Optional[Sequence[str]] = None,
        max_inferred_indicators: int = 3,
        max_inferred_areas: int = 3,
        k_doc_passages: int = 5,
    ) -> Dict[str, Any]:
        inferred_indicators = match_indicators_in_query(question, self.indicator_catalog, max_matches=max_inferred_indicators)
        inferred_areas = match_areas_in_query(question, self.area_catalog, max_matches=max_inferred_areas)

        indicators: List[IndicatorSpec] = list(inferred_indicators)
        if explicit_sdg_indicators:
            for code in explicit_sdg_indicators:
                spec = self._indicator_by_sdg.get(code) or self._indicator_by_series.get(code)
                if spec and spec not in indicators:
                    indicators.append(spec)

        areas: List[str] = list(inferred_areas)
        if explicit_areas:
            for a in explicit_areas:
                if a not in areas:
                    areas.append(a)

        sdg_summaries: List[str] = []
        sdg_series_payload: List[Dict[str, Any]] = []
        if self.fao_data_fetcher and indicators and areas:
            for spec in indicators:
                for area in areas:
                    try:
                        series = self.fao_data_fetcher(spec.series_code, area) or {}
                    except Exception as e:
                        logger.warning("Failed to fetch SDG data for %s / %s: %s", spec.series_code, area, e)
                        series = {}

                    sdg_summaries.append(self._summarize_timeseries(spec, area, series))
                    sdg_series_payload.append(
                        {"sdg_indicator": spec.sdg_indicator, "series_code": spec.series_code, "area": area, "series": series}
                    )

        passages = self.pathways_index.retrieve(question, k=k_doc_passages)

        answer = self._call_model(
            question=question,
            passages=passages,
            indicators=indicators,
            areas=areas,
            sdg_summaries=sdg_summaries,
        )

        return {
            "answer": answer,
            "indicators": indicators,
            "areas": areas,
            "doc_passages": passages,
            "sdg_data_summaries": sdg_summaries,
            "sdg_series": sdg_series_payload,
        }

    def _summarize_timeseries(self, spec: IndicatorSpec, area: str, series: Dict[int, float]) -> str:
        if not series:
            return (
                f"No numeric SDG data was available for {spec.sdg_indicator} / {spec.series_code} "
                f"({spec.name}) in {area}. Acknowledge this gap."
            )

        years = sorted(series.keys())
        values = [series[y] for y in years]

        start_year, end_year = years[0], years[-1]
        start_val, end_val = values[0], values[-1]
        min_val, max_val = min(values), max(values)

        if end_val > start_val * 1.05:
            trend = "increased"
        elif end_val < start_val * 0.95:
            trend = "decreased"
        else:
            trend = "remained relatively stable"

        series_str = "; ".join(f"{y}: {series[y]:.2f}" for y in years[-10:])  # last ~10 points to limit prompt size
        return (
            f"For {area}, {spec.name} (SDG {spec.sdg_indicator}, series {spec.series_code}) {trend} "
            f"from {start_year} ({start_val:.2f}) to {end_year} ({end_val:.2f}); "
            f"range ≈ [{min_val:.2f}, {max_val:.2f}]. Recent values: {series_str}."
        )

    def _call_model(
        self,
        question: str,
        passages: Sequence[RetrievedChunk],
        indicators: Sequence[IndicatorSpec],
        areas: Sequence[str],
        sdg_summaries: Sequence[str],
    ) -> str:
        indicators_block = "\n".join(
            f"- SDG {s.sdg_indicator} ({s.series_code}): {s.name}" for s in indicators
        ) or "None inferred."
        areas_block = "\n".join(f"- {a}" for a in areas) or "None inferred."  # FIXED

        sdg_block = "\n\n".join(sdg_summaries) or "No SDG time-series context was available."

        passages_block_parts: List[str] = []
        for p in passages:
            passages_block_parts.append(f"[Pathways for Peace, p.{p.page}, score={p.score:.3f}] {p.text}")
        passages_block = "\n\n".join(passages_block_parts) or "No relevant passages were retrieved."

        user_prompt = f"""
User question:
{question}

Selected / inferred SDG indicators:
{indicators_block}

Selected / inferred areas:
{areas_block}

SDG data context (summaries):
{sdg_block}

Report context (Pathways for Peace excerpts):
{passages_block}

Task:
Write a conflict-sensitive agricultural policy response. Include:
1) Situation snapshot (use SDG trends above)
2) Conflict risk analysis (draw on Pathways excerpts above; cite pages like p.X)
3) Policy options (near-term / medium-term / structural) + implementation safeguards
4) Monitoring & learning plan (which SDG indicators to track + disaggregation suggestions)
5) Key uncertainties + what to collect next
"""

        response = self.client.responses.create(
            model=self.model,
            instructions=AGRICULTURAL_POLICY_SYSTEM_PROMPT,
            input=user_prompt,
        )

        return getattr(response, "output_text", str(response))