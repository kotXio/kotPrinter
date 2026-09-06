import {
  ApiError,
  isAbortError,
  isApiErrorEnvelope,
} from './errors';
import type {
  CheckResponse,
  DeleteJobResponse,
  HealthResponse,
  HistoryCleanupRequest,
  HistoryCleanupResponse,
  HistoryResponse,
  ImageJobRequest,
  InstallDryRunResponse,
  JobActionResponse,
  JobArtifactUrls,
  JobDetailResponse,
  JobResponse,
  JobsResponse,
  PrinterInfoResponse,
  PrinterStatusResponse,
  QueueResponse,
  SettingsConfig,
  SettingsResponse,
  SettingsUpdateResponse,
  SettingsValidationResponse,
  TextJobRequest,
  VersionResponse,
} from './types';

export const DEFAULT_API_BASE_URL = '/api';

export type HttpMethod = 'GET' | 'POST' | 'PUT' | 'DELETE';

export type QueryValue = string | number | boolean | null | undefined;
export type QueryParams = Record<string, QueryValue | QueryValue[]>;

export type ApiUrlOptions = {
  baseUrl?: string;
  query?: QueryParams;
};

export type ApiRequestOptions = ApiUrlOptions & {
  signal?: AbortSignal;
  headers?: HeadersInit;
};

export type JsonRequestOptions = ApiRequestOptions & {
  method?: HttpMethod;
  body?: unknown;
};

export type ApiClientConfig = {
  baseUrl?: string;
};

export type ListParams = {
  limit?: number;
};

export function apiUrl(path: string, options: ApiUrlOptions = {}): string {
  const baseUrl = options.baseUrl ?? DEFAULT_API_BASE_URL;
  const base = baseUrl.replace(/\/+$/, '');
  const apiPath = normalizeApiPath(path, base);
  const url = apiPath ? `${base}/${apiPath}` : base;
  const query = toSearchParams(options.query);

  if (!query) {
    return url;
  }

  return `${url}?${query}`;
}

export function previewUrl(jobId: string, options: ApiUrlOptions = {}): string {
  return jobArtifactUrl(jobId, 'preview', options);
}

export function sourceUrl(jobId: string, options: ApiUrlOptions = {}): string {
  return jobArtifactUrl(jobId, 'source', options);
}

export function rasterUrl(jobId: string, options: ApiUrlOptions = {}): string {
  return jobArtifactUrl(jobId, 'raster', options);
}

export function jobArtifactUrls(
  jobId: string,
  options: ApiUrlOptions = {},
): JobArtifactUrls {
  return {
    previewUrl: previewUrl(jobId, options),
    sourceUrl: sourceUrl(jobId, options),
    rasterUrl: rasterUrl(jobId, options),
  };
}

export async function requestJson<T>(
  path: string,
  options: JsonRequestOptions = {},
): Promise<T> {
  const headers = new Headers(options.headers);
  const init: RequestInit = {
    method: options.method ?? (options.body === undefined ? 'GET' : 'POST'),
    headers,
    signal: options.signal,
  };

  if (options.body !== undefined) {
    if (!headers.has('Content-Type')) {
      headers.set('Content-Type', 'application/json');
    }
    init.body = JSON.stringify(options.body);
  }

  return sendJson<T>(path, init, options);
}

export async function requestMultipart<T>(
  path: string,
  formData: FormData,
  options: ApiRequestOptions = {},
): Promise<T> {
  return sendJson<T>(
    path,
    {
      method: 'POST',
      headers: options.headers,
      body: formData,
      signal: options.signal,
    },
    options,
  );
}

export function createImageJobForm(
  file: File,
  payload: ImageJobRequest = {},
): FormData {
  const formData = new FormData();
  formData.append('file', file, file.name);

  if (payload.preset) {
    formData.append('preset', payload.preset);
  }

  if (payload.render !== undefined) {
    formData.append('render', String(payload.render));
  }

  if (payload.options && Object.keys(payload.options).length > 0) {
    formData.append('options', JSON.stringify(payload.options));
  }

  return formData;
}

export async function getHealth(options?: ApiRequestOptions): Promise<HealthResponse> {
  return requestJson<HealthResponse>('/health', options);
}

export async function getVersion(options?: ApiRequestOptions): Promise<VersionResponse> {
  return requestJson<VersionResponse>('/version', options);
}

export async function getCheck(
  live = false,
  options?: ApiRequestOptions,
): Promise<CheckResponse> {
  return requestJson<CheckResponse>(live ? '/check/live' : '/check', options);
}

export async function getPrinterStatus(
  options?: ApiRequestOptions,
): Promise<PrinterStatusResponse> {
  return requestJson<PrinterStatusResponse>('/printer/status', options);
}

export async function getPrinterInfo(
  options?: ApiRequestOptions,
): Promise<PrinterInfoResponse> {
  return requestJson<PrinterInfoResponse>('/printer/info', options);
}

export async function getSettings(
  options?: ApiRequestOptions,
): Promise<SettingsResponse> {
  return requestJson<SettingsResponse>('/settings', options);
}

export async function validateSettings(
  settings: Partial<SettingsConfig>,
  options?: ApiRequestOptions,
): Promise<SettingsValidationResponse> {
  return requestJson<SettingsValidationResponse>('/settings/validate', {
    ...options,
    method: 'POST',
    body: settings,
  });
}

export async function updateSettings(
  settings: Partial<SettingsConfig>,
  options?: ApiRequestOptions,
): Promise<SettingsUpdateResponse> {
  return requestJson<SettingsUpdateResponse>('/settings', {
    ...options,
    method: 'PUT',
    body: settings,
  });
}

export async function createTextJob(
  payload: TextJobRequest,
  options?: ApiRequestOptions,
): Promise<JobResponse> {
  return requestJson<JobResponse>('/jobs/text', {
    ...options,
    method: 'POST',
    body: payload,
  });
}

export async function createImageJob(
  file: File,
  payload: ImageJobRequest = {},
  options?: ApiRequestOptions,
): Promise<JobResponse> {
  return requestMultipart<JobResponse>(
    '/jobs/image',
    createImageJobForm(file, payload),
    options,
  );
}

export async function listJobs(
  params: ListParams = {},
  options?: ApiRequestOptions,
): Promise<JobsResponse> {
  return requestJson<JobsResponse>('/jobs', {
    ...options,
    query: params,
  });
}

export async function getJob(
  jobId: string,
  options?: ApiRequestOptions,
): Promise<JobDetailResponse> {
  return requestJson<JobDetailResponse>(`/jobs/${encodeURIComponent(jobId)}`, options);
}

export async function printJob(
  jobId: string,
  options?: ApiRequestOptions,
): Promise<JobActionResponse> {
  return requestJson<JobActionResponse>(`/jobs/${encodeURIComponent(jobId)}/print`, {
    ...options,
    method: 'POST',
  });
}

export async function reprintJob(
  jobId: string,
  options?: ApiRequestOptions,
): Promise<JobActionResponse> {
  return requestJson<JobActionResponse>(`/jobs/${encodeURIComponent(jobId)}/reprint`, {
    ...options,
    method: 'POST',
  });
}

export async function cancelJob(
  jobId: string,
  options?: ApiRequestOptions,
): Promise<JobActionResponse> {
  return requestJson<JobActionResponse>(`/jobs/${encodeURIComponent(jobId)}/cancel`, {
    ...options,
    method: 'POST',
  });
}

export async function deleteJob(
  jobId: string,
  options?: ApiRequestOptions,
): Promise<DeleteJobResponse> {
  return requestJson<DeleteJobResponse>(`/jobs/${encodeURIComponent(jobId)}`, {
    ...options,
    method: 'DELETE',
  });
}

export async function getQueue(options?: ApiRequestOptions): Promise<QueueResponse> {
  return requestJson<QueueResponse>('/queue', options);
}

export async function getHistory(
  params: ListParams = {},
  options?: ApiRequestOptions,
): Promise<HistoryResponse> {
  return requestJson<HistoryResponse>('/history', {
    ...options,
    query: params,
  });
}

export async function cleanupHistory(
  payload: HistoryCleanupRequest = {},
  options?: ApiRequestOptions,
): Promise<HistoryCleanupResponse> {
  return requestJson<HistoryCleanupResponse>('/history/cleanup', {
    ...options,
    method: 'POST',
    body: payload,
  });
}

export async function installDryRun(
  options?: ApiRequestOptions,
): Promise<InstallDryRunResponse> {
  return requestJson<InstallDryRunResponse>('/system/install/dry-run', {
    ...options,
    method: 'POST',
  });
}

export function createApiClient(config: ApiClientConfig = {}) {
  const baseUrl = config.baseUrl ?? DEFAULT_API_BASE_URL;
  const withBase = <T extends ApiRequestOptions | undefined>(options: T) => ({
    ...options,
    baseUrl: options?.baseUrl ?? baseUrl,
  });
  const withBaseUrl = (options?: ApiUrlOptions): ApiUrlOptions => ({
    ...options,
    baseUrl: options?.baseUrl ?? baseUrl,
  });

  return {
    apiUrl: (path: string, options?: ApiUrlOptions) => apiUrl(path, withBaseUrl(options)),
    previewUrl: (jobId: string, options?: ApiUrlOptions) => previewUrl(jobId, withBaseUrl(options)),
    sourceUrl: (jobId: string, options?: ApiUrlOptions) => sourceUrl(jobId, withBaseUrl(options)),
    rasterUrl: (jobId: string, options?: ApiUrlOptions) => rasterUrl(jobId, withBaseUrl(options)),
    jobArtifactUrls: (jobId: string, options?: ApiUrlOptions) => (
      jobArtifactUrls(jobId, withBaseUrl(options))
    ),
    requestJson: <T>(path: string, options?: JsonRequestOptions) => (
      requestJson<T>(path, withBase(options))
    ),
    requestMultipart: <T>(path: string, formData: FormData, options?: ApiRequestOptions) => (
      requestMultipart<T>(path, formData, withBase(options))
    ),
    getHealth: (options?: ApiRequestOptions) => getHealth(withBase(options)),
    getVersion: (options?: ApiRequestOptions) => getVersion(withBase(options)),
    getCheck: (live = false, options?: ApiRequestOptions) => getCheck(live, withBase(options)),
    getPrinterStatus: (options?: ApiRequestOptions) => getPrinterStatus(withBase(options)),
    getPrinterInfo: (options?: ApiRequestOptions) => getPrinterInfo(withBase(options)),
    getSettings: (options?: ApiRequestOptions) => getSettings(withBase(options)),
    validateSettings: (settings: Partial<SettingsConfig>, options?: ApiRequestOptions) => (
      validateSettings(settings, withBase(options))
    ),
    updateSettings: (settings: Partial<SettingsConfig>, options?: ApiRequestOptions) => (
      updateSettings(settings, withBase(options))
    ),
    createTextJob: (payload: TextJobRequest, options?: ApiRequestOptions) => (
      createTextJob(payload, withBase(options))
    ),
    createImageJob: (file: File, payload?: ImageJobRequest, options?: ApiRequestOptions) => (
      createImageJob(file, payload, withBase(options))
    ),
    listJobs: (params?: ListParams, options?: ApiRequestOptions) => (
      listJobs(params, withBase(options))
    ),
    getJob: (jobId: string, options?: ApiRequestOptions) => getJob(jobId, withBase(options)),
    printJob: (jobId: string, options?: ApiRequestOptions) => printJob(jobId, withBase(options)),
    reprintJob: (jobId: string, options?: ApiRequestOptions) => reprintJob(jobId, withBase(options)),
    cancelJob: (jobId: string, options?: ApiRequestOptions) => cancelJob(jobId, withBase(options)),
    deleteJob: (jobId: string, options?: ApiRequestOptions) => deleteJob(jobId, withBase(options)),
    getQueue: (options?: ApiRequestOptions) => getQueue(withBase(options)),
    getHistory: (params?: ListParams, options?: ApiRequestOptions) => (
      getHistory(params, withBase(options))
    ),
    cleanupHistory: (payload?: HistoryCleanupRequest, options?: ApiRequestOptions) => (
      cleanupHistory(payload, withBase(options))
    ),
    installDryRun: (options?: ApiRequestOptions) => installDryRun(withBase(options)),
  };
}

export const apiClient = createApiClient();

async function sendJson<T>(
  path: string,
  init: RequestInit,
  options: ApiUrlOptions,
): Promise<T> {
  const url = apiUrl(path, options);
  let response: Response;

  try {
    response = await fetch(url, init);
  } catch (error) {
    if (isAbortError(error)) {
      throw error;
    }

    throw new ApiError('Network request failed', {
      status: 0,
      code: 'network_error',
      url,
      payload: error,
    });
  }

  const payload = await readJsonPayload(response);

  if (!response.ok || isApiErrorEnvelope(payload)) {
    throw ApiError.fromResponse(response, payload);
  }

  return payload as T;
}

async function readJsonPayload(response: Response): Promise<unknown> {
  const text = await response.text();

  if (!text) {
    return undefined;
  }

  const contentType = response.headers.get('Content-Type') ?? '';
  if (!contentType.includes('application/json')) {
    if (response.ok) {
      throw new ApiError('Expected JSON response from API', {
        status: response.status,
        statusText: response.statusText,
        url: response.url,
        code: 'invalid_response',
        payload: text,
      });
    }
    return text;
  }

  try {
    return JSON.parse(text);
  } catch (error) {
    throw new ApiError('Invalid JSON response from API', {
      status: response.status,
      statusText: response.statusText,
      url: response.url,
      code: 'invalid_json_response',
      payload: text,
      details: error,
    });
  }
}

function jobArtifactUrl(
  jobId: string,
  artifact: 'preview' | 'source' | 'raster',
  options: ApiUrlOptions,
): string {
  return apiUrl(`/jobs/${encodeURIComponent(jobId)}/${artifact}`, options);
}

function normalizeApiPath(path: string, normalizedBase: string): string {
  let apiPath = path.replace(/^\/+/, '');

  if (normalizedBase.endsWith('/api')) {
    if (apiPath === 'api') {
      return '';
    }
    if (apiPath.startsWith('api/')) {
      apiPath = apiPath.slice(4);
    }
  }

  return apiPath;
}

function toSearchParams(query: QueryParams | undefined): string {
  if (!query) {
    return '';
  }

  const params = new URLSearchParams();

  for (const [key, value] of Object.entries(query)) {
    const values = Array.isArray(value) ? value : [value];
    for (const item of values) {
      if (item === null || item === undefined) {
        continue;
      }
      params.append(key, String(item));
    }
  }

  return params.toString();
}
