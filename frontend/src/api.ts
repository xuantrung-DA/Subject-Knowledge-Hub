let csrf = "";
export function setCsrf(value: string) {
  csrf = value;
}
export class ApiError extends Error {
  constructor(
    public code: string,
    message: string,
    public status = 0,
  ) {
    super(message);
  }
}
function messageFrom(data: unknown, status: number): ApiError {
  const d = data as {
    error?: { code?: string; message?: string };
    detail?: unknown;
    request_id?: string;
  } | null;
  const message =
    d?.error?.message ||
    (typeof d?.detail === "string"
      ? d.detail
      : status === 413
        ? "Tệp vượt quá giới hạn dung lượng cho phép."
        : status === 401
          ? "Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại."
          : `Không thể hoàn tất yêu cầu (HTTP ${status}).`);
  return new ApiError(
    d?.error?.code || `http_${status}`,
    message + (d?.request_id ? ` · Request: ${d.request_id}` : ""),
    status,
  );
}
export async function api<T>(
  path: string,
  init: RequestInit = {},
  timeout = 120000,
): Promise<T> {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), timeout);
  const headers = new Headers(init.headers);
  if (init.body && !(init.body instanceof FormData))
    headers.set("Content-Type", "application/json");
  if (init.method && init.method !== "GET") headers.set("X-CSRF-Token", csrf);
  try {
    const response = await fetch(`/api${path}`, {
      ...init,
      headers,
      credentials: "same-origin",
      signal: controller.signal,
    });
    const data =
      response.status === 204 ? null : await response.json().catch(() => null);
    if (!response.ok) {
      if (response.status === 401 && !path.startsWith("/auth/"))
        window.dispatchEvent(new Event("session-expired"));
      throw messageFrom(data, response.status);
    }
    return data as T;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    if (error instanceof DOMException && error.name === "AbortError")
      throw new ApiError(
        "timeout",
        "Yêu cầu quá thời gian chờ. Máy chủ có thể vẫn đang xử lý; hãy tải lại lịch sử/trạng thái trước khi thử lại.",
      );
    throw new ApiError(
      "network",
      "Không kết nối được máy chủ. Kiểm tra ứng dụng đã khởi động rồi thử lại.",
    );
  } finally {
    window.clearTimeout(timer);
  }
}
export function upload<T>(
  path: string,
  form: FormData,
  progress: (percent: number) => void,
): Promise<T> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `/api${path}`);
    xhr.withCredentials = true;
    xhr.timeout = 600000;
    xhr.setRequestHeader("X-CSRF-Token", csrf);
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) progress(Math.round((e.loaded / e.total) * 100));
    };
    xhr.onload = () => {
      let data: unknown = null;
      try {
        data = JSON.parse(xhr.responseText);
      } catch {
        /* Non-JSON proxy response uses HTTP status. */
      }
      if (xhr.status >= 200 && xhr.status < 300) resolve(data as T);
      else {
        if (xhr.status === 401)
          window.dispatchEvent(new Event("session-expired"));
        reject(messageFrom(data, xhr.status));
      }
    };
    xhr.onerror = () =>
      reject(
        new ApiError(
          "network",
          "Mất kết nối khi upload. Hãy tải lại danh sách trước khi upload lại.",
        ),
      );
    xhr.ontimeout = () =>
      reject(
        new ApiError(
          "timeout",
          "Upload quá thời gian chờ. Hãy kiểm tra danh sách tài liệu trước khi thử lại.",
        ),
      );
    xhr.send(form);
  });
}
export const post = <T>(path: string, body: unknown = {}) =>
  api<T>(path, { method: "POST", body: JSON.stringify(body) });
export const errorText = (error: unknown) =>
  error instanceof Error ? error.message : "Đã xảy ra lỗi. Vui lòng thử lại.";
