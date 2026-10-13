import type { ApiErrorBody } from './types';

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  constructor(status: number, body: ApiErrorBody) {
    super(body.message);
    this.name = 'ApiError';
    this.status = status;
    this.code = body.error_code;
  }
}

/** Map any thrown error to an i18n key under "errors.*" so screens show a translated message. */
export function errorMessageKey(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 429 || err.status === 503 || err.code === 'busy') return 'errors.busy';
    if (err.code === 'unsupported_file_type') return 'errors.fileType';
    if (err.code === 'file_too_large') return 'errors.fileSize';
    if (err.code === 'network') return 'errors.network';
    if (err.status === 401) return 'errors.signedOut';
    if (err.code === 'bad_response') return 'errors.generic';
  }
  return 'errors.generic';
}
