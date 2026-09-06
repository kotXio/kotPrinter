export type ApiProblem = {
  code: string;
  message: string;
  field?: string;
  details?: unknown;
  partial?: boolean;
  queueId?: string;
  [key: string]: unknown;
};

export type ApiFieldError = {
  field: string;
  message: string;
  code?: string;
};

export type ApiErrorEnvelope = {
  ok: false;
  error: ApiProblem;
};

export type ApiErrorInit = {
  status: number;
  statusText?: string;
  url?: string;
  code?: string;
  field?: string;
  details?: unknown;
  payload?: unknown;
  fieldErrors?: ApiFieldError[];
  partial?: boolean;
};

export class ApiError extends Error {
  readonly status: number;
  readonly statusText: string;
  readonly url: string;
  readonly code: string;
  readonly field?: string;
  readonly details?: unknown;
  readonly payload?: unknown;
  readonly fieldErrors: ApiFieldError[];
  readonly partial: boolean;

  constructor(message: string, init: ApiErrorInit) {
    super(message);
    this.name = 'ApiError';
    this.status = init.status;
    this.statusText = init.statusText ?? '';
    this.url = init.url ?? '';
    this.code = init.code ?? 'api_error';
    this.field = init.field;
    this.details = init.details;
    this.payload = init.payload;
    this.fieldErrors = init.fieldErrors ?? [];
    this.partial = init.partial ?? false;
  }

  static fromResponse(response: Response, payload: unknown): ApiError {
    const problem = problemFromPayload(payload);
    const fieldErrors = fieldErrorsFromPayload(payload, problem);

    return new ApiError(problem.message || response.statusText || 'API request failed', {
      status: response.status,
      statusText: response.statusText,
      url: response.url,
      code: problem.code,
      field: problem.field,
      details: problem.details,
      payload,
      fieldErrors,
      partial: problem.partial,
    });
  }
}

export function isApiError(value: unknown): value is ApiError {
  return value instanceof ApiError;
}

export function isAbortError(value: unknown): value is DOMException {
  return value instanceof DOMException && value.name === 'AbortError';
}

export function isApiErrorEnvelope(value: unknown): value is ApiErrorEnvelope {
  if (!isRecord(value) || value.ok !== false || !isRecord(value.error)) {
    return false;
  }

  return typeof value.error.code === 'string'
    && typeof value.error.message === 'string';
}

export function messageFromError(value: unknown): string {
  if (value instanceof ApiError) {
    return value.message;
  }

  if (value instanceof Error) {
    return value.message;
  }

  if (typeof value === 'string') {
    return value;
  }

  return 'Unknown error';
}

function problemFromPayload(payload: unknown): ApiProblem {
  if (isApiErrorEnvelope(payload)) {
    return payload.error;
  }

  if (isRecord(payload)) {
    const message = typeof payload.message === 'string'
      ? payload.message
      : 'API request failed';
    const code = typeof payload.code === 'string'
      ? payload.code
      : 'api_error';

    return { code, message };
  }

  if (typeof payload === 'string' && payload.trim()) {
    return {
      code: 'api_error',
      message: payload,
    };
  }

  return {
    code: 'api_error',
    message: 'API request failed',
  };
}

function fieldErrorsFromPayload(
  payload: unknown,
  problem: ApiProblem,
): ApiFieldError[] {
  const errors: ApiFieldError[] = [];

  if (problem.field) {
    errors.push({
      field: problem.field,
      message: problem.message,
      code: problem.code,
    });
  }

  if (isRecord(problem.details)) {
    appendIssueList(errors, problem.details.errors, problem.code);
  }

  if (isRecord(payload)) {
    appendIssueList(errors, payload.errors, problem.code);
  }

  return dedupeFieldErrors(errors);
}

function appendIssueList(
  errors: ApiFieldError[],
  value: unknown,
  fallbackCode?: string,
) {
  if (!Array.isArray(value)) {
    return;
  }

  for (const item of value) {
    if (!isRecord(item)) {
      continue;
    }

    const field = typeof item.field === 'string' ? item.field : undefined;
    const message = typeof item.message === 'string' ? item.message : undefined;

    if (!field || !message) {
      continue;
    }

    errors.push({
      field,
      message,
      code: typeof item.code === 'string' ? item.code : fallbackCode,
    });
  }
}

function dedupeFieldErrors(errors: ApiFieldError[]): ApiFieldError[] {
  const seen = new Set<string>();
  return errors.filter((error) => {
    const key = `${error.field}\n${error.message}`;
    if (seen.has(key)) {
      return false;
    }
    seen.add(key);
    return true;
  });
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}
