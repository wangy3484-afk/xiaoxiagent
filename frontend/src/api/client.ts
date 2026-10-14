export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
    public readonly code?: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export async function apiRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  if (!headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(`/api/v1${path}`, {
    credentials: "include",
    ...init,
    headers,
  });

  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as {
      detail?: { code?: string; message?: string };
    } | null;
    throw new ApiError(
      response.status,
      payload?.detail?.message ?? `请求失败（${response.status}）`,
      payload?.detail?.code,
    );
  }

  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}
