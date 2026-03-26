from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

import httpx
from tenacity import AsyncRetrying, retry_if_exception, stop_after_attempt, wait_exponential_jitter

from app.gmail.dto import ThreadPayload

logger = logging.getLogger(__name__)

GMAIL_BASE = "https://gmail.googleapis.com/gmail/v1/users/me"


class GmailHttpError(Exception):
    def __init__(self, status_code: int, body: str) -> None:
        self.status_code = status_code
        self.body = body
        super().__init__(f"Gmail HTTP {status_code}: {body[:200]}")


def _retryable_gmail(exc: BaseException) -> bool:
    if isinstance(exc, (httpx.TimeoutException, httpx.NetworkError)):
        return True
    if isinstance(exc, GmailHttpError):
        return exc.status_code == 429 or exc.status_code >= 500
    return False


def _header_value(headers: list[dict[str, str]], name: str) -> str | None:
    for h in headers:
        if h.get("name", "").lower() == name.lower():
            return h.get("value")
    return None


def _parse_thread_get(payload: dict[str, Any]) -> ThreadPayload:
    tid = payload.get("id") or ""
    snippet = payload.get("snippet") or ""
    messages = payload.get("messages") or []
    subject = ""
    from_addr: str | None = None
    internal_date = int(datetime.now(tz=UTC).timestamp() * 1000)
    if messages:
        first = messages[0]
        internal_date = int(first.get("internalDate", internal_date))
        headers = first.get("payload", {}).get("headers", [])
        subject = _header_value(headers, "Subject") or ""
        from_addr = _header_value(headers, "From")
    return ThreadPayload(
        gmail_thread_id=tid,
        subject=subject or "(no subject)",
        snippet=snippet,
        internal_date=internal_date,
        from_addr=from_addr,
    )


class GmailClient:
    def __init__(self, http: httpx.AsyncClient) -> None:
        self._http = http

    async def _get_json(
        self,
        url: str,
        headers: dict[str, str],
        params: dict[str, str] | list[tuple[str, str]] | None = None,
    ) -> dict[str, Any]:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(5),
            wait=wait_exponential_jitter(initial=1, max=60),
            retry=retry_if_exception(_retryable_gmail),
            reraise=True,
        ):
            with attempt:
                r = await self._http.get(url, headers=headers, params=params, timeout=60.0)
                if r.status_code == 429:
                    raise GmailHttpError(429, r.text)
                if r.status_code >= 500:
                    raise GmailHttpError(r.status_code, r.text)
                if r.status_code >= 400:
                    raise GmailHttpError(r.status_code, r.text)
                return r.json()

    async def list_thread_ids(
        self,
        access_token: str,
        *,
        max_results: int = 20,
        page_token: str | None = None,
        q: str | None = None,
    ) -> tuple[list[str], str | None]:
        params: dict[str, str] = {"maxResults": str(max_results)}
        if page_token:
            params["pageToken"] = page_token
        if q:
            params["q"] = q
        url = f"{GMAIL_BASE}/threads"
        data = await self._get_json(
            url,
            headers={"Authorization": f"Bearer {access_token}"},
            params=params,
        )
        threads = data.get("threads") or []
        ids = [t["id"] for t in threads if "id" in t]
        next_token = data.get("nextPageToken")
        return ids, next_token

    async def get_thread_metadata(self, access_token: str, thread_id: str) -> ThreadPayload:
        url = f"{GMAIL_BASE}/threads/{thread_id}"
        params = [
            ("format", "metadata"),
            ("metadataHeaders", "Subject"),
            ("metadataHeaders", "From"),
            ("metadataHeaders", "Date"),
        ]
        data = await self._get_json(
            url,
            headers={"Authorization": f"Bearer {access_token}"},
            params=params,
        )
        return _parse_thread_get(data)


async def fetch_threads_page_details(
    client: GmailClient,
    access_token: str,
    thread_ids: list[str],
    *,
    max_parallel: int = 10,
) -> list[ThreadPayload]:
    sem = __import__("asyncio").Semaphore(max_parallel)

    async def one(tid: str) -> ThreadPayload:
        async with sem:
            return await client.get_thread_metadata(access_token, tid)

    import asyncio

    return list(await asyncio.gather(*[one(t) for t in thread_ids]))
