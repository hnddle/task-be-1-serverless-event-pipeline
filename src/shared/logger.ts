/**
 * 구조화 JSON 로거 + Application Insights 연동.
 *
 * 모든 로그를 JSON 형식으로 stdout에 출력한다.
 * Application Insights가 활성화되면 trackTrace/trackException으로 구조화 프로퍼티를 전송한다.
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

// Application Insights TelemetryClient (null이면 미연동 상태)
let _telemetryClient: import('applicationinsights').TelemetryClient | null = null;

const AI_SEVERITY_MAP: Record<LogLevel, string> = {
  DEBUG: 'Verbose',
  INFO: 'Information',
  WARNING: 'Warning',
  ERROR: 'Error',
};

function buildLogEntry(level: LogLevel, message: string, extra: Record<string, unknown>): LogEntry {
  const entry: LogEntry = {
    timestamp: new Date().toISOString(),
    level,
    correlation_id: getCorrelationId(),
    message,
  };

  const logContext = getLogContext();
  Object.assign(entry, logContext);
  Object.assign(entry, extra);

  return entry;
}

function cleanEntry(entry: LogEntry): Record<string, unknown> {
  return Object.fromEntries(
    Object.entries(entry).filter(([, v]) => v !== null && v !== undefined),
  );
}

function trackToAppInsights(entry: LogEntry): void {
  if (!_telemetryClient) return;

  // 구조화 프로퍼티를 customDimensions로 전송
  const properties: Record<string, string> = {};
  for (const [key, value] of Object.entries(entry)) {
    if (key !== 'message' && key !== 'timestamp' && key !== 'level' && value != null) {
      properties[key] = String(value);
    }
  }

  if (entry.level === 'ERROR') {
    _telemetryClient.trackException({
      exception: new Error(entry.message),
      severity: AI_SEVERITY_MAP[entry.level],
      properties,
    });
  } else {
    _telemetryClient.trackTrace({
      message: entry.message,
      severity: AI_SEVERITY_MAP[entry.level],
      properties,
    });
  }
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
      const entry = buildLogEntry('INFO', message, { logger: name, ...extra });
      console.log(JSON.stringify(cleanEntry(entry)));
      trackToAppInsights(entry);
    },
    warn(message: string, extra: Record<string, unknown> = {}): void {
      const entry = buildLogEntry('WARNING', message, { logger: name, ...extra });
      console.warn(JSON.stringify(cleanEntry(entry)));
      trackToAppInsights(entry);
    },
    error(message: string, extra: Record<string, unknown> = {}): void {
      const entry = buildLogEntry('ERROR', message, { logger: name, ...extra });
      console.error(JSON.stringify(cleanEntry(entry)));
      trackToAppInsights(entry);
    },
    debug(message: string, extra: Record<string, unknown> = {}): void {
      const entry = buildLogEntry('DEBUG', message, { logger: name, ...extra });
      console.log(JSON.stringify(cleanEntry(entry)));
      trackToAppInsights(entry);
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
    appInsights
      .setup(connectionString)
      .setAutoCollectConsole(true, true)
      .setAutoCollectExceptions(true)
      .setAutoCollectRequests(true)
      .setAutoCollectDependencies(true)
      .start();

    _telemetryClient = appInsights.defaultClient;

    const logger = getLogger();
    logger.info('Application Insights 연동 완료');
  } catch {
    const logger = getLogger();
    logger.warn('Application Insights 연동 실패 - 로컬 stdout 로깅만 사용');
  }
}

/** 테스트용 - telemetry client 리셋 */
export function _resetTelemetryClient(): void {
  _telemetryClient = null;
}
