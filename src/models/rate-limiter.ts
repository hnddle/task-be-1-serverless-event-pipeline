/**
 * Rate Limiter 상태 타입.
 *
 * Cosmos DB `rate-limiter` 컨테이너 문서 구조와 1:1 대응.
 * SPEC.md §3.4 참조.
 */

export interface RateLimiterDocument {
  id: string;
  tokens: number;
  max_tokens: number;
  last_refill_at: string;
  updated_at: string;
  _etag?: string;
}
