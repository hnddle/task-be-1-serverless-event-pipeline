/**
 * 구조화 JSON 로거.
 *
 * 모든 로그를 JSON 형식으로 stdout에 출력한다.
 * correlation_id는 AsyncLocalStorage에서 자동으로 가져와 포함한다.
 * 파일 로깅 금지 — 12-Factor XI: Logs.
 *
 * SPEC.md §10.2 참조.
 */

import { getCorrelationId, getLogContext } from './correlation';

export type LogLevel = 'INFO' | 'WARNING' | 'ERROR' | 'DEBUG';

interface LogEntry {
  timestamp: string;
  level: LogLevel;
  correlation_id: string | null;
  message: string;
  [key: string]: unknown;
}

function buildLogEntry(level: LogLevel, message: string, extra: Record<string, unknown>): string {
  const entry: LogEntry = {
    timestamp: new Date().toISOString(),
    level,
    correlation_id: getCorrelationId(),
    message,
  };

  // contextvars(AsyncLocalStorage)에서 추가 로그 필드 병합
  const logContext = getLogContext();
  Object.assign(entry, logContext);

  // extra 필드 병합
  Object.assign(entry, extra);

  // null/undefined 값 필드 제거
  const cleaned = Object.fromEntries(
    Object.entries(entry).filter(([, v]) => v !== null && v !== undefined),
  );

  return JSON.stringify(cleaned);
}

export interface Logger {
  info(message: string, extra?: Record<string, unknown>): void;
  warn(message: string, extra?: Record<string, unknown>): void;
  error(message: string, extra?: Record<string, unknown>): void;
  debug(message: string, extra?: Record<string, unknown>): void;
}

function createLogger(name: string): Logger {
  return {
    info(message: string, extra: Record<string, unknown> = {}): void {
      process.stdout.write(buildLogEntry('INFO', message, { logger: name, ...extra }) + '\n');
    },
    warn(message: string, extra: Record<string, unknown> = {}): void {
      process.stdout.write(buildLogEntry('WARNING', message, { logger: name, ...extra }) + '\n');
    },
    error(message: string, extra: Record<string, unknown> = {}): void {
      process.stderr.write(buildLogEntry('ERROR', message, { logger: name, ...extra }) + '\n');
    },
    debug(message: string, extra: Record<string, unknown> = {}): void {
      process.stdout.write(buildLogEntry('DEBUG', message, { logger: name, ...extra }) + '\n');
    },
  };
}

const loggerCache = new Map<string, Logger>();

export function getLogger(name?: string): Logger {
  const loggerName = name ? `notification-pipeline.${name}` : 'notification-pipeline';
  let logger = loggerCache.get(loggerName);
  if (!logger) {
    logger = createLogger(loggerName);
    loggerCache.set(loggerName, logger);
  }
  return logger;
}

export function logWithContext(
  logger: Logger,
  level: LogLevel,
  message: string,
  extra: Record<string, unknown> = {},
): void {
  switch (level) {
    case 'INFO':
      logger.info(message, extra);
      break;
    case 'WARNING':
      logger.warn(message, extra);
      break;
    case 'ERROR':
      logger.error(message, extra);
      break;
    case 'DEBUG':
      logger.debug(message, extra);
      break;
  }
}

export function setupApplicationInsights(connectionString?: string): void {
  if (!connectionString) return;

  try {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const appInsights = require('applicationinsights') as typeof import('applicationinsights');
    appInsights.setup(connectionString).setAutoCollectConsole(true).start();
  } catch {
    const logger = getLogger();
    logger.warn('applicationinsights 패키지를 로드할 수 없�� Application Insights 연동을 건너뜁니다');
  }
}
