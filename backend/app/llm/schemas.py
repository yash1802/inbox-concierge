from typing import Any

from pydantic import BaseModel, Field

# OpenAI Structured Outputs (strict): must match ThreadClassificationItem / BatchClassificationResult.
# See https://platform.openai.com/docs/guides/structured-outputs
CLASSIFICATION_RESPONSE_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "results": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "gmail_thread_id": {"type": "string"},
                    "categories": {"type": "array", "items": {"type": "string"}},
                    "reason": {"type": "string"},
                    "confidence": {"type": "number"},
                },
                "required": ["gmail_thread_id", "categories", "reason", "confidence"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["results"],
    "additionalProperties": False,
}


class ThreadClassificationItem(BaseModel):
    gmail_thread_id: str
    categories: list[str] = Field(default_factory=list)
    reason: str = ""
    confidence: float = Field(ge=0.0, le=1.0, default=0.5)


class BatchClassificationResult(BaseModel):
    results: list[ThreadClassificationItem]
