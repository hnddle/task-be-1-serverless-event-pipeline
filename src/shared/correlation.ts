/**
 * Correlation ID 컨텍스트 관리.
 *
 * AsyncLocalStorage 기반으로 함수 실행 컨텍스트에 correlation_id를 바인딩한다.
 * 모든 함수 진입점에서 setCorrelationId()를 호출하면,
 * 해당 컨텍스트 내 모든 로그에 correlation_id가 자동 포함된다.
 *
 * SPEC.md §10.1 참조.
 */

import { AsyncLocalStorage } from 'node:async_hooks';
import { v4 as uuidv4 } from 'uuid';

interface CorrelationContext {
  correlationId: string | null;
  logContext: Record<string, unknown>;
}

const storage = new AsyncLocalStorage<CorrelationContext>();

export function generateCorrelationId(): string {
  return uuidv4();
}

export function setCorrelationId(correlationId: string): void {
  const ctx = storage.getStore();
  if (ctx) {
    ctx.correlationId = correlationId;
  }
}

export function getCorrelationId(): string | null {
  return storage.getStore()?.correlationId ?? null;
}

export function setLogContext(fields: Record<string, unknown>): void {
  const ctx = storage.getStore();
  if (ctx) {
    Object.assign(ctx.logContext, fields);
  }
}

export function getLogContext(): Record<string, unknown> {
  return storage.getStore()?.logContext ?? {};
}

export function clearContext(): void {
  const ctx = storage.getStore();
  if (ctx) {
    ctx.correlationId = null;
    ctx.logContext = {};
  }
}

/**
 * 컨텍스트를 초기화하고 콜백을 실행한다.
 * Azure Functions 진입점에서 사용.
 */
export function runWithContext<T>(fn: () => T): T {
  return storage.run({ correlationId: null, logContext: {} }, fn);
}
