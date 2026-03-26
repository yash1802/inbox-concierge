from pydantic import BaseModel, Field


class ThreadClassificationItem(BaseModel):
    gmail_thread_id: str
    categories: list[str] = Field(default_factory=list)
    reason: str = ""
    confidence: float = Field(ge=0.0, le=1.0, default=0.5)


class BatchClassificationResult(BaseModel):
    results: list[ThreadClassificationItem]
