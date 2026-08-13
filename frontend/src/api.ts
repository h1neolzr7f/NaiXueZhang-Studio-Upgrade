declare global {
  interface Window {
    ApiClient?: {
      get: (path: string, options?: Record<string, unknown>) => Promise<unknown>;
      post: (path: string, body?: unknown, options?: Record<string, unknown>) => Promise<unknown>;
      fetchJson: (path: string, options?: Record<string, unknown>) => Promise<unknown>;
      pollJob: (
        taskId: string,
        onProgress?: (job: Record<string, unknown>) => void,
        options?: Record<string, unknown>,
      ) => Promise<Record<string, unknown>>;
    };
  }
}

export class ApiError extends Error {
  status: number;
  payload: unknown;

  constructor(message: string, status: number, payload: unknown) {
    super(message);
    this.status = status;
    this.payload = payload;
  }
}

function client() {
  const api = window.ApiClient;
  if (!api) {
    throw new ApiError("ApiClient missing", 500, null);
  }
  return api;
}

export function get<T>(path: string, options?: Record<string, unknown>): Promise<T> {
  return client().get(path, options) as Promise<T>;
}

export function post<T>(
  path: string,
  body: unknown,
  options?: Record<string, unknown>,
): Promise<T> {
  return client().post(path, body, options) as Promise<T>;
}

export function del<T>(path: string): Promise<T> {
  return client().fetchJson(path, { method: "DELETE" }) as Promise<T>;
}

export function pollJob(
  taskId: string,
  onProgress?: (job: Record<string, unknown>) => void,
  options?: Record<string, unknown>,
): Promise<Record<string, unknown>> {
  return client().pollJob(taskId, onProgress, options);
}
