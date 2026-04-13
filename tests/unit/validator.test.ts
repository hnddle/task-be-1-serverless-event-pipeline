/**
 * POST /events 입력 검증 테스트.
 */

import { v4 as uuidv4 } from 'uuid';
import { v1 as uuidv1 } from 'uuid';
import { ValidationError } from '@src/shared/errors';
import { validateCreateEvent } from '@src/shared/validator';

const VALID_BODY = {
  id: uuidv4(),
  event_type: 'appointment_confirmed',
  clinic_id: 'CLINIC_123',
  patient_id: 'PATIENT_456',
  channels: ['email', 'sms'],
};

function makeBody(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return { ...VALID_BODY, ...overrides };
}

describe('유효한 요청 검증', () => {
  it('모든 필드가 유효하면 검증을 통과한다', () => {
    const result = validateCreateEvent(VALID_BODY);
    expect(result.clinic_id).toBe('CLINIC_123');
  });

  it('email, sms, webhook 모든 채널을 포함한 요청이 통과한다', () => {
    const body = makeBody({ channels: ['email', 'sms', 'webhook'] });
    const result = validateCreateEvent(body);
    expect(result.channels).toHaveLength(3);
  });

  it('채널이 1개만 있어도 통과한다', () => {
    const body = makeBody({ channels: ['webhook'] });
    const result = validateCreateEvent(body);
    expect(result.channels).toHaveLength(1);
  });

  it('모든 event_type이 통과한다', () => {
    for (const et of ['appointment_confirmed', 'insurance_approved', 'claim_completed']) {
      const body = makeBody({ event_type: et });
      const result = validateCreateEvent(body);
      expect(result.event_type).toBe(et);
    }
  });
});

describe('id 필드 검증', () => {
  it('UUID 형식이 아닌 id는 에러가 발생한다', () => {
    const body = makeBody({ id: 'not-a-uuid' });
    try {
      validateCreateEvent(body);
      fail('Expected ValidationError');
    } catch (err) {
      expect(err).toBeInstanceOf(ValidationError);
      const details = (err as ValidationError).toDict().details as { field: string }[];
      expect(details.some((d) => d.field === 'id')).toBe(true);
    }
  });

  it('id가 누락되면 에러가 발생한다', () => {
    const { id: _, ...body } = VALID_BODY;
    try {
      validateCreateEvent(body);
      fail('Expected ValidationError');
    } catch (err) {
      expect(err).toBeInstanceOf(ValidationError);
      const details = (err as ValidationError).toDict().details as { field: string }[];
      expect(details.some((d) => d.field === 'id')).toBe(true);
    }
  });

  it('UUID v1은 거부된다', () => {
    const body = makeBody({ id: uuidv1() });
    try {
      validateCreateEvent(body);
      fail('Expected ValidationError');
    } catch (err) {
      expect(err).toBeInstanceOf(ValidationError);
      const details = (err as ValidationError).toDict().details as { field: string }[];
      expect(details.some((d) => d.field === 'id')).toBe(true);
    }
  });
});

describe('event_type 필드 검증', () => {
  it('지원하지 않는 event_type은 에러가 발생한다', () => {
    const body = makeBody({ event_type: 'order_placed' });
    try {
      validateCreateEvent(body);
      fail('Expected ValidationError');
    } catch (err) {
      expect(err).toBeInstanceOf(ValidationError);
      const details = (err as ValidationError).toDict().details as { field: string; message: string }[];
      const fieldDetail = details.find((d) => d.field === 'event_type');
      expect(fieldDetail).toBeDefined();
      expect(fieldDetail!.message).toContain('appointment_confirmed');
      expect(fieldDetail!.message).toContain('insurance_approved');
      expect(fieldDetail!.message).toContain('claim_completed');
    }
  });

  it('event_type이 누락되면 에러가 발생한다', () => {
    const { event_type: _, ...body } = VALID_BODY;
    try {
      validateCreateEvent(body);
      fail('Expected ValidationError');
    } catch (err) {
      expect(err).toBeInstanceOf(ValidationError);
      const details = (err as ValidationError).toDict().details as { field: string }[];
      expect(details.some((d) => d.field === 'event_type')).toBe(true);
    }
  });
});

describe('clinic_id 필드 검증', () => {
  it('빈 문자열 clinic_id는 에러가 발생한다', () => {
    const body = makeBody({ clinic_id: '' });
    try {
      validateCreateEvent(body);
      fail('Expected ValidationError');
    } catch (err) {
      expect(err).toBeInstanceOf(ValidationError);
      const details = (err as ValidationError).toDict().details as { field: string }[];
      expect(details.some((d) => d.field === 'clinic_id')).toBe(true);
    }
  });

  it('공백만 있는 clinic_id는 에러가 발생한다', () => {
    const body = makeBody({ clinic_id: '   ' });
    try {
      validateCreateEvent(body);
      fail('Expected ValidationError');
    } catch (err) {
      expect(err).toBeInstanceOf(ValidationError);
      const details = (err as ValidationError).toDict().details as { field: string }[];
      expect(details.some((d) => d.field === 'clinic_id')).toBe(true);
    }
  });

  it('clinic_id가 누락되면 에러가 발생한다', () => {
    const { clinic_id: _, ...body } = VALID_BODY;
    try {
      validateCreateEvent(body);
      fail('Expected ValidationError');
    } catch (err) {
      expect(err).toBeInstanceOf(ValidationError);
      const details = (err as ValidationError).toDict().details as { field: string }[];
      expect(details.some((d) => d.field === 'clinic_id')).toBe(true);
    }
  });
});

describe('patient_id 필드 검증', () => {
  it('빈 문자열 patient_id는 에러가 발생한다', () => {
    const body = makeBody({ patient_id: '' });
    try {
      validateCreateEvent(body);
      fail('Expected ValidationError');
    } catch (err) {
      expect(err).toBeInstanceOf(ValidationError);
      const details = (err as ValidationError).toDict().details as { field: string }[];
      expect(details.some((d) => d.field === 'patient_id')).toBe(true);
    }
  });

  it('patient_id가 누락되면 에러가 발생한다', () => {
    const { patient_id: _, ...body } = VALID_BODY;
    try {
      validateCreateEvent(body);
      fail('Expected ValidationError');
    } catch (err) {
      expect(err).toBeInstanceOf(ValidationError);
      const details = (err as ValidationError).toDict().details as { field: string }[];
      expect(details.some((d) => d.field === 'patient_id')).toBe(true);
    }
  });
});

describe('channels 필드 검증', () => {
  it('빈 channels 배열은 에러가 발생한다', () => {
    const body = makeBody({ channels: [] });
    try {
      validateCreateEvent(body);
      fail('Expected ValidationError');
    } catch (err) {
      expect(err).toBeInstanceOf(ValidationError);
      const details = (err as ValidationError).toDict().details as { field: string }[];
      expect(details.some((d) => d.field === 'channels')).toBe(true);
    }
  });

  it('중복 채널은 에러가 발생한다', () => {
    const body = makeBody({ channels: ['email', 'email'] });
    try {
      validateCreateEvent(body);
      fail('Expected ValidationError');
    } catch (err) {
      expect(err).toBeInstanceOf(ValidationError);
      const details = (err as ValidationError).toDict().details as { field: string; message: string }[];
      const channelDetail = details.find((d) => d.field === 'channels');
      expect(channelDetail).toBeDefined();
      expect(channelDetail!.message).toContain('Duplicate');
    }
  });

  it('지원하지 않는 채널은 에러가 발생한다', () => {
    const body = makeBody({ channels: ['email', 'push'] });
    try {
      validateCreateEvent(body);
      fail('Expected ValidationError');
    } catch (err) {
      expect(err).toBeInstanceOf(ValidationError);
      const details = (err as ValidationError).toDict().details as { field: string }[];
      expect(details.length).toBeGreaterThan(0);
    }
  });

  it('channels가 누락되면 에러가 발생한다', () => {
    const { channels: _, ...body } = VALID_BODY;
    try {
      validateCreateEvent(body);
      fail('Expected ValidationError');
    } catch (err) {
      expect(err).toBeInstanceOf(ValidationError);
      const details = (err as ValidationError).toDict().details as { field: string }[];
      expect(details.some((d) => d.field === 'channels')).toBe(true);
    }
  });

  it('channels가 배열이 아니면 에러가 발생한다', () => {
    const body = makeBody({ channels: 'email' });
    try {
      validateCreateEvent(body);
      fail('Expected ValidationError');
    } catch (err) {
      expect(err).toBeInstanceOf(ValidationError);
      const details = (err as ValidationError).toDict().details as { field: string }[];
      expect(details.some((d) => d.field === 'channels')).toBe(true);
    }
  });
});

describe('에러 응답 형식', () => {
  it('ValidationError.toDict()가 SPEC §8.4 형식을 따른다', () => {
    const body = makeBody({ id: 'invalid', event_type: 'unknown', channels: [] });
    try {
      validateCreateEvent(body);
      fail('Expected ValidationError');
    } catch (err) {
      expect(err).toBeInstanceOf(ValidationError);
      const errorDict = (err as ValidationError).toDict();
      expect(errorDict.error).toBe('VALIDATION_ERROR');
      expect(errorDict.message).toBe('Invalid request body');
      expect(Array.isArray(errorDict.details)).toBe(true);
      expect((errorDict.details as unknown[]).length).toBeGreaterThan(0);
    }
  });

  it('여러 필드가 동시에 실패하면 모든 에러가 details에 포함된다', () => {
    const body = { channels: [] };
    try {
      validateCreateEvent(body);
      fail('Expected ValidationError');
    } catch (err) {
      expect(err).toBeInstanceOf(ValidationError);
      const details = (err as ValidationError).toDict().details as { field: string }[];
      const fields = new Set(details.map((d) => d.field));
      expect(fields).toContain('id');
      expect(fields).toContain('event_type');
      expect(fields).toContain('clinic_id');
      expect(fields).toContain('patient_id');
    }
  });

  it('각 detail 항목에 field와 message가 있다', () => {
    const body = makeBody({ id: 'bad' });
    try {
      validateCreateEvent(body);
      fail('Expected ValidationError');
    } catch (err) {
      expect(err).toBeInstanceOf(ValidationError);
      const details = (err as ValidationError).toDict().details as { field: string; message: string }[];
      for (const detail of details) {
        expect(detail).toHaveProperty('field');
        expect(detail).toHaveProperty('message');
      }
    }
  });
});
