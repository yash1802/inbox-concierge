from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from openai import AsyncOpenAI
from openai import RateLimitError as OpenAIRateLimitError
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession
from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from app.config import Settings
from app.db.models import LlmOperation, LlmRun
from app.gmail.dto import ThreadPayload
from app.llm.prompts import build_classification_messages, classification_response_format
from app.llm.schemas import BatchClassificationResult, ThreadClassificationItem

logger = logging.getLogger(__name__)


def _validate_against_allowed(
    items: list[ThreadClassificationItem], allowed: set[str]
) -> list[ThreadClassificationItem]:
    out: list[ThreadClassificationItem] = []
    allowed_lower = {a.lower(): a for a in allowed}
    for it in items:
        fixed_cats: list[str] = []
        for c in it.categories:
            key = c.strip()
            if key in allowed:
                fixed_cats.append(key)
            elif key.lower() in allowed_lower:
                fixed_cats.append(allowed_lower[key.lower()])
        out.append(
            ThreadClassificationItem(
                gmail_thread_id=it.gmail_thread_id,
                categories=list(dict.fromkeys(fixed_cats)),
                reason=it.reason,
                confidence=it.confidence,
            )
        )
    return out


async def classify_threads_batch(
    *,
    session: AsyncSession,
    settings: Settings,
    user_id: uuid.UUID,
    job_id: uuid.UUID | None,
    operation: LlmOperation,
    allowed_labels: list[str],
    threads: list[ThreadPayload],
) -> list[ThreadClassificationItem]:
    if not threads:
        return []
    client = AsyncOpenAI(api_key=settings.openai_api_key)
    messages = build_classification_messages(allowed_labels, threads)
    input_payload: dict[str, Any] = {
        "prompt_style": "static_system_cached_plus_user_json",
        "structured_outputs": True,
        "allowed_labels": allowed_labels,
        "threads": [
            {
                "gmail_thread_id": t.gmail_thread_id,
                "subject": t.subject,
                "snippet": t.snippet,
                "internal_date": t.internal_date,
                "from_addr": t.from_addr,
            }
            for t in threads
        ],
    }
    allowed_set = set(allowed_labels)

    async for attempt in AsyncRetrying(
        stop=stop_after_attempt(5),
        wait=wait_exponential_jitter(initial=1, max=60),
        retry=retry_if_exception_type((OpenAIRateLimitError,)),
        reraise=True,
    ):
        with attempt:
            resp = await client.chat.completions.create(
                model=settings.llm_model,
                messages=messages,
                response_format=classification_response_format(),
                temperature=0.2,
            )
            break

    raw = resp.choices[0].message.content or "{}"
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.exception("LLM returned non-JSON")
        raise ValueError("LLM returned invalid JSON") from e

    if not isinstance(parsed, dict):
        raise ValueError("LLM JSON must be an object")

    results_raw = parsed.get("results")
    if results_raw is None:
        raise ValueError("LLM JSON missing results")

    try:
        batch = BatchClassificationResult.model_validate({"results": results_raw})
    except ValidationError as e:
        logger.warning("Validation failed, attempting recovery: %s", e)
        batch = BatchClassificationResult.model_validate({"results": []})

    by_id = {t.gmail_thread_id for t in threads}
    filtered = [r for r in batch.results if r.gmail_thread_id in by_id]
    if len(filtered) < len(threads):
        missing = by_id - {r.gmail_thread_id for r in filtered}
        for mid in missing:
            filtered.append(
                ThreadClassificationItem(
                    gmail_thread_id=mid,
                    categories=[],
                    reason="model omitted thread",
                    confidence=0.0,
                )
            )

    validated = _validate_against_allowed(filtered, allowed_set)

    avg_conf = sum(v.confidence for v in validated) / len(validated) if validated else None
    first_reason = validated[0].reason if validated else None

    output_payload: dict[str, Any] = {
        "raw_model_text": raw,
        "results": [r.model_dump() for r in validated],
    }
    session.add(
        LlmRun(
            user_id=user_id,
            job_id=job_id,
            thread_id=None,
            operation=operation.value,
            model=settings.llm_model,
            input_payload=input_payload,
            output_payload=output_payload,
            reason=first_reason,
            confidence=avg_conf,
        )
    )
    await session.flush()

    return validated
