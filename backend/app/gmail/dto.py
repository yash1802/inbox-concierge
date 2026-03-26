from dataclasses import dataclass


@dataclass(frozen=True)
class ThreadPayload:
    gmail_thread_id: str
    subject: str
    snippet: str
    internal_date: int
    from_addr: str | None
