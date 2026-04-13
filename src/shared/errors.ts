/**
 * 공통 예외 클래스.
 *
 * API 경계에서 사용되는 표준 에러 타입.
 * SPEC.md §8.4 공통 에러 응답 형식 참조.
 */

export interface FieldError {
  field: string;
  message: string;
}

export class AppError extends Error {
  readonly errorCode: string;
  readonly statusCode: number;

  constructor(errorCode: string, message: string, statusCode: number = 500) {
    super(message);
    this.name = 'AppError';
    this.errorCode = errorCode;
    this.statusCode = statusCode;
  }

  toDict(): Record<string, unknown> {
    return {
      error: this.errorCode,
      message: this.message,
      details: [],
    };
  }
}

export class ValidationError extends AppError {
  readonly details: FieldError[];

  constructor(message: string = 'Invalid request body', details: FieldError[] = []) {
    super('VALIDATION_ERROR', message, 400);
    this.name = 'ValidationError';
    this.details = details;
  }

  override toDict(): Record<string, unknown> {
    return {
      error: this.errorCode,
      message: this.message,
      details: this.details.map((d) => ({ field: d.field, message: d.message })),
    };
  }
}

export class NotFoundError extends AppError {
  constructor(message: string = 'Resource not found') {
    super('NOT_FOUND', message, 404);
    this.name = 'NotFoundError';
  }
}

export class ConflictError extends AppError {
  constructor(message: string = 'Resource conflict') {
    super('CONFLICT', message, 409);
    this.name = 'ConflictError';
  }
}
