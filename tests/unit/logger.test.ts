/**
 * 구조화 로거 및 Correlation ID 컨텍스트 테스트.
 */

import {
  clearContext,
  generateCorrelationId,
  getCorrelationId,
  getLogContext,
  runWithContext,
  setCorrelationId,
  setLogContext,
} from '@src/shared/correlation';
import { getLogger, logWithContext } from '@src/shared/logger';

describe('Correlation ID 컨텍스트 관리', () => {
  it('생성된 correlation_id가 UUID 형식이다', () => {
    runWithContext(() => {
      const cid = generateCorrelationId();
      expect(cid).toHaveLength(36);
      expect(cid.split('-')).toHaveLength(5);
    });
  });

  it('correlation_id를 설정하고 조회할 수 있다', () => {
    runWithContext(() => {
      setCorrelationId('test-cid-123');
      expect(getCorrelationId()).toBe('test-cid-123');
    });
  });

  it('기본값은 null이다', () => {
    runWithContext(() => {
      expect(getCorrelationId()).toBeNull();
    });
  });

  it('clearContext()로 초기화된다', () => {
    runWithContext(() => {
      setCorrelationId('test-cid');
      clearContext();
      expect(getCorrelationId()).toBeNull();
    });
  });

  it('추가 로그 컨텍스트를 설정하고 조회할 수 있다', () => {
    runWithContext(() => {
      setLogContext({ event_id: 'evt-1', channel: 'email' });
      const ctx = getLogContext();
      expect(ctx.event_id).toBe('evt-1');
      expect(ctx.channel).toBe('email');
    });
  });

  it('setLogContext는 기존 필드를 유지하며 새 필드를 추가한다', () => {
    runWithContext(() => {
      setLogContext({ event_id: 'evt-1' });
      setLogContext({ channel: 'sms' });
      const ctx = getLogContext();
      expect(ctx.event_id).toBe('evt-1');
      expect(ctx.channel).toBe('sms');
    });
  });

  it('clearContext()로 로그 컨텍스트도 초기화된다', () => {
    runWithContext(() => {
      setLogContext({ event_id: 'evt-1' });
      clearContext();
      expect(getLogContext()).toEqual({});
    });
  });
});

describe('JSON 구조화 로거 출력 형식', () => {
  let stdoutSpy: jest.SpyInstance;
  let stderrSpy: jest.SpyInstance;

  beforeEach(() => {
    stdoutSpy = jest.spyOn(process.stdout, 'write').mockImplementation(() => true);
    stderrSpy = jest.spyOn(process.stderr, 'write').mockImplementation(() => true);
  });

  function getLastStdoutLog(): Record<string, unknown> {
    const calls = stdoutSpy.mock.calls;
    const lastLine = calls[calls.length - 1][0] as string;
    return JSON.parse(lastLine.trim());
  }

  function getLastStderrLog(): Record<string, unknown> {
    const calls = stderrSpy.mock.calls;
    const lastLine = calls[calls.length - 1][0] as string;
    return JSON.parse(lastLine.trim());
  }

  it('로그가 JSON 형식으로 출력된다', () => {
    runWithContext(() => {
      const logger = getLogger('test-json-output');
      logger.info('테스트 메시지');
      const entry = getLastStdoutLog();
      expect(entry.message).toBe('테스트 메시지');
      expect(entry.level).toBe('INFO');
      expect(entry).toHaveProperty('timestamp');
    });
  });

  it('correlation_id가 컨텍스트에 설정되면 로그에 포함된다', () => {
    runWithContext(() => {
      setCorrelationId('cid-test-456');
      const logger = getLogger('test-cid-include');
      logger.info('상관관계 테스트');
      const entry = getLastStdoutLog();
      expect(entry.correlation_id).toBe('cid-test-456');
    });
  });

  it('correlation_id가 설정되지 않으면 필드가 제외된다', () => {
    runWithContext(() => {
      const logger = getLogger('test-cid-omit');
      logger.info('메시지');
      const entry = getLastStdoutLog();
      expect(entry).not.toHaveProperty('correlation_id');
    });
  });

  it('setLogContext로 설정한 필드가 로그에 포함된다', () => {
    runWithContext(() => {
      setLogContext({ event_id: 'evt-789', channel: 'webhook' });
      const logger = getLogger('test-ctx-fields');
      logger.info('컨텍스트 테스트');
      const entry = getLastStdoutLog();
      expect(entry.event_id).toBe('evt-789');
      expect(entry.channel).toBe('webhook');
    });
  });

  it('logWithContext로 전달한 extra 필드가 로그에 포함된다', () => {
    runWithContext(() => {
      const logger = getLogger('test-extra');
      logWithContext(logger, 'INFO', '발송 완료', {
        duration_ms: 150,
        provider: 'sendgrid',
      });
      const entry = getLastStdoutLog();
      expect(entry.message).toBe('발송 완료');
      expect(entry.duration_ms).toBe(150);
      expect(entry.provider).toBe('sendgrid');
    });
  });

  it('ERROR 레벨은 stderr에 출력된다', () => {
    runWithContext(() => {
      const logger = getLogger('test-error');
      logger.error('에러 발생');
      const entry = getLastStderrLog();
      expect(entry.message).toBe('에러 발생');
      expect(entry.level).toBe('ERROR');
    });
  });

  it('WARNING 레벨이 정확히 출력된다', () => {
    runWithContext(() => {
      const logger = getLogger('test-warn');
      logger.warn('경고 메시지');
      const entry = getLastStdoutLog();
      expect(entry.level).toBe('WARNING');
    });
  });
});

describe('getLogger 유틸리티', () => {
  it('name을 지정하면 하위 로거 이름이 반환된다', () => {
    // getLogger는 내부적으로 notification-pipeline.{name} 형식을 사용
    // 직접 로거 이름을 검증할 수 없으나 로그 출력에서 logger 필드를 확인
    const stdoutSpy = jest.spyOn(process.stdout, 'write').mockImplementation(() => true);
    const logger = getLogger('event-api');
    runWithContext(() => {
      logger.info('test');
      const entry = JSON.parse((stdoutSpy.mock.calls[0][0] as string).trim());
      expect(entry.logger).toBe('notification-pipeline.event-api');
    });
  });

  it('name 없이 호출하면 기본 로거 이름을 사용한다', () => {
    const stdoutSpy = jest.spyOn(process.stdout, 'write').mockImplementation(() => true);
    const logger = getLogger();
    runWithContext(() => {
      logger.info('test');
      const entry = JSON.parse((stdoutSpy.mock.calls[0][0] as string).trim());
      expect(entry.logger).toBe('notification-pipeline');
    });
  });
});
