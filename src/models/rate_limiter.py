"""Rate Limiter 상태 Pydantic 모델.

Cosmos DB `rate-limiter` 컨테이너 문서 구조와 1:1 대응.
SPEC.md §3.4 참조.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class RateLimiterDocument(BaseModel):
    """Rate Limiter 상태 문서 (Cosmos DB `rate-limiter` 컨테이너).

    id는 `{channel}:{provider}` 형식이며 Partition Key를 겸한다.
    _etag는 낙관적 동시성 제어에 사용된다.
    TTL은 60초로 자동 만료.
    """

    id: str
    tokens: float
    max_tokens: float
    last_refill_at: datetime
    updated_at: datetime
    etag: str | None = Field(default=None, alias="_etag")

    model_config = {"populate_by_name": True}
