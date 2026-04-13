/**
 * POST /events 요청 입력 검증.
 *
 * Zod 기반으로 요청 바디를 검증한다.
 * 검증 실패 시 ValidationError (errors.ts)를 발생시킨다.
 *
 * SPEC.md §8.1 입력 검증 규칙 참조.
 */

import { z } from 'zod';
import { CHANNEL_TYPES, EVENT_TYPES } from '../models/events';
import { ValidationError } from './errors';
import type { FieldError } from './errors';

export const createEventSchema = z
  .object({
    event_type: z.enum(EVENT_TYPES as [string, ...string[]], {
      errorMap: () => ({ message: `Must be one of: ${EVENT_TYPES.join(', ')}` }),
    }),
    clinic_id: z
      .string({ required_error: 'clinic_id is required' })
      .refine((v) => v.trim().length > 0, { message: 'Must not be empty' }),
    patient_id: z
      .string({ required_error: 'patient_id is required' })
      .refine((v) => v.trim().length > 0, { message: 'Must not be empty' }),
    channels: z
      .array(
        z.enum(CHANNEL_TYPES as [string, ...string[]], {
          errorMap: () => ({ message: `Must be one of: ${CHANNEL_TYPES.join(', ')}` }),
        }),
      )
      .min(1, 'Must contain at least one channel')
      .refine((arr) => new Set(arr).size === arr.length, {
        message: 'Duplicate channels are not allowed',
      }),
  })
  .strict();

export type CreateEventRequest = z.infer<typeof createEventSchema>;

export function validateCreateEvent(body: unknown): CreateEventRequest {
  const result = createEventSchema.safeParse(body);

  if (result.success) {
    return result.data;
  }

  const details: FieldError[] = result.error.issues.map((issue) => {
    const field = issue.path.length > 0 ? String(issue.path[issue.path.length - 1]) : 'unknown';

    if (issue.code === 'invalid_type' && issue.received === 'undefined') {
      return { field, message: `${field} is required` };
    }

    if (issue.code === 'invalid_type' && issue.expected === 'string') {
      return { field, message: 'Must be a string' };
    }

    if (issue.code === 'invalid_type' && issue.expected === 'array') {
      return { field, message: 'Must be an array' };
    }

    return { field, message: issue.message };
  });

  throw new ValidationError('Invalid request body', details);
}
