"""Inference server for Nosana GPU nodes.

Exposes a simple HTTP interface to decouple the inference model from
Nosana-specific APIs. Runs on a Nosana GPU node.

Endpoints:
    POST /embed    generate embeddings for text batches
    POST /resolve  LLM-assisted resolution suggestion
    GET  /health   health check
    GET  /         service info
"""

from __future__ import annotations

import os
import time
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "sentence-transformers/all-mpnet-base-v2")
EMBEDDING_DIMENSIONS = 768
LLM_MODEL = os.environ.get("LLM_MODEL", "Qwen/Qwen2.5-3B-Instruct")

app = FastAPI(
    title="Inference Server",
    description="Embedding and resolution service for Nosana-deployed ML inference.",
    version="0.1.0",
)

_embed_model: Any = None
_llm_model: Any = None
_llm_tokenizer: Any = None


def _get_embed_model() -> Any:
    global _embed_model
    if _embed_model is None:
        from sentence_transformers import SentenceTransformer

        _embed_model = SentenceTransformer(EMBEDDING_MODEL)
    return _embed_model


def _get_llm() -> tuple[Any, Any]:
    global _llm_model, _llm_tokenizer
    if _llm_model is None or _llm_tokenizer is None:
        from transformers import AutoModelForCausalLM, AutoTokenizer

        _llm_tokenizer = AutoTokenizer.from_pretrained(LLM_MODEL, trust_remote_code=True)
        _llm_model = AutoModelForCausalLM.from_pretrained(
            LLM_MODEL,
            device_map="auto",
            trust_remote_code=True,
            load_in_4bit=True,
        )
    return _llm_model, _llm_tokenizer


class EmbedRequest(BaseModel):
    texts: list[str] = Field(min_length=1)
    model: str | None = None


class EmbedResponse(BaseModel):
    embeddings: list[list[float]]
    model: str
    duration_ms: int


class ResolveRequest(BaseModel):
    exception_context: dict[str, Any]
    prompt_template: str = "resolution_v2"


class ResolveResponse(BaseModel):
    resolution_suggestion: str
    confidence: float
    reasoning: str


class HealthResponse(BaseModel):
    status: str
    model: str | None = None


@app.get("/")
async def root() -> dict[str, str]:
    return {
        "service": "inference-server",
        "version": "0.1.0",
        "model": EMBEDDING_MODEL,
        "dimensions": str(EMBEDDING_DIMENSIONS),
    }


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    if _embed_model is None:
        return HealthResponse(status="starting", model=None)
    return HealthResponse(status="healthy", model=EMBEDDING_MODEL)


@app.post("/embed", response_model=EmbedResponse)
async def embed(request: EmbedRequest) -> EmbedResponse:
    model = _get_embed_model()
    start = time.monotonic()
    vectors = model.encode(request.texts, convert_to_numpy=True)
    duration_ms = int((time.monotonic() - start) * 1000)
    embeddings = [v.tolist() for v in vectors]
    return EmbedResponse(
        embeddings=embeddings,
        model=EMBEDDING_MODEL,
        duration_ms=duration_ms,
    )


_RESOLVE_PROMPT_TEMPLATE = """You are a financial reconciliation assistant. Given a transaction and its candidate matches, determine the best resolution.

Transaction:
{direction} {amount} {currency} on {date}
Description: {description}
Source: {source_adapter}
Reference: {reference}

Candidate matches:
{candidates}

Respond with a JSON object:
- "suggestion": "ACCEPT" or "REJECT" or "REVIEW"
- "confidence": a float between 0.0 and 1.0
- "reasoning": a short explanation for the suggestion
"""


@app.post("/resolve", response_model=ResolveResponse)
async def resolve(request: ResolveRequest) -> ResolveResponse:
    try:
        model, tokenizer = _get_llm()
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to load LLM model ({LLM_MODEL}): {exc}",
        )

    ctx = request.exception_context
    candidates_formatted = _format_candidates(ctx.get("candidates", []))

    prompt = _RESOLVE_PROMPT_TEMPLATE.format(
        direction=ctx.get("direction", "UNKNOWN"),
        amount=ctx.get("amount", "0"),
        currency=ctx.get("currency", "USD"),
        date=ctx.get("date", "unknown"),
        description=ctx.get("description", ""),
        source_adapter=ctx.get("source_adapter", "unknown"),
        reference=ctx.get("reference", ""),
        candidates=candidates_formatted,
    )

    try:
        start = time.monotonic()
        inputs = tokenizer(prompt, return_tensors="pt").to(model.device)
        outputs = model.generate(
            **inputs,
            max_new_tokens=256,
            temperature=0.1,
            do_sample=True,
        )
        response_text = tokenizer.decode(outputs[0], skip_special_tokens=True)
        duration_ms = int((time.monotonic() - start) * 1000)

        parsed = _parse_llm_response(response_text, prompt)
        return ResolveResponse(
            resolution_suggestion=parsed.get("suggestion", "REVIEW"),
            confidence=float(parsed.get("confidence", 0.5)),
            reasoning=parsed.get("reasoning", f"LLM suggestion generated in {duration_ms}ms."),
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"LLM inference failed: {exc}",
        )


def _format_candidates(candidates: list[dict]) -> str:
    if not candidates:
        return "  No candidates available."
    lines = []
    for i, c in enumerate(candidates[:5], 1):
        lines.append(
            f"  {i}. {c.get('amount', '?')} {c.get('currency', '')} "
            f"| similarity: {c.get('cosine_similarity', '?')} "
            f"| {c.get('description', '')}"
        )
    return "\n".join(lines)


def _parse_llm_response(response_text: str, prompt: str) -> dict[str, Any]:
    import json
    import re

    json_match = re.search(r"\{[^}]+\}", response_text[len(prompt) :])
    if json_match:
        try:
            return json.loads(json_match.group())
        except (json.JSONDecodeError, ValueError):
            pass

    return {"suggestion": "REVIEW", "confidence": 0.5, "reasoning": "Could not parse LLM response."}
