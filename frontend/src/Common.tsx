import { useEffect, useRef } from "react";
import type { ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

export function Icon({
  name = "book",
  size = 20,
}: {
  name?: string;
  size?: number;
}) {
  const paths: Record<string, ReactNode> = {
    book: (
      <>
        <path d="M12 6c-3-3-7-3-10-2v15c4-1 7-1 10 2 3-3 6-3 10-2V4c-3-1-7-1-10 2Z" />
        <path d="M12 6v15" />
      </>
    ),
    plus: <path d="M12 5v14M5 12h14" />,
    upload: (
      <>
        <path d="M12 16V3m-5 5 5-5 5 5M4 16v5h16v-5" />
      </>
    ),
    file: (
      <>
        <path d="M14 2H5v20h14V7Z" />
        <path d="M14 2v5h5M8 12h8m-8 4h6" />
      </>
    ),
    chat: (
      <path d="M21 11a9 9 0 0 1-9 9 10 10 0 0 1-4-1l-6 2 2-6a9 9 0 1 1 17-4Z" />
    ),
    chart: (
      <>
        <path d="M4 3v18h17M8 17v-5m5 5V7m5 10v-8" />
      </>
    ),
    arrow: <path d="M4 12h16m-6-6 6 6-6 6" />,
    close: <path d="m6 6 12 12M18 6 6 18" />,
    refresh: (
      <>
        <path d="M20 10a8 8 0 0 0-14-5L3 8m0-5v5h5M4 14a8 8 0 0 0 14 5l3-3m0 5v-5h-5" />
      </>
    ),
    check: <path d="m5 12 4 4L19 6" />,
    logout: (
      <>
        <path d="M9 4H3v16h6m5-13 5 5-5 5m-7-5h12" />
      </>
    ),
    link: (
      <>
        <path d="m10 14 4-4m-6 6-1 1a4 4 0 0 1-6-6l5-5a4 4 0 0 1 6 0m0 12a4 4 0 0 0 6 0l5-5a4 4 0 0 0-6-6l-1 1" />
      </>
    ),
  };
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.65"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {paths[name] || paths.book}
    </svg>
  );
}
export const activeStatus = (status: string) =>
  ["queued", "parsing", "chunking", "embedding", "running"].includes(status);
export const statusNames: Record<string, string> = {
  queued: "Đang chờ",
  parsing: "Đọc PDF",
  chunking: "Chia nội dung",
  embedding: "Lập chỉ mục",
  running: "Đang chạy",
  ready: "Sẵn sàng",
  failed: "Thất bại",
  needs_ocr: "Cần OCR",
  cancelled: "Đã hủy",
  pending: "Chưa chạy",
  imported: "Đã nhập",
};
export function Status({ status }: { status: string }) {
  return (
    <span
      className={`badge ${status === "ready" ? "good" : status === "failed" ? "bad" : status === "needs_ocr" ? "warn" : activeStatus(status) ? "working" : ""}`}
    >
      {activeStatus(status) && <span className="status-dot" />}
      {statusNames[status] || status}
    </span>
  );
}
export function ErrorBox({
  error,
  onRetry,
}: {
  error: string | null;
  onRetry?: () => void;
}) {
  return error ? (
    <div className="notice error" role="alert">
      <span>{error}</span>
      {onRetry && (
        <button className="small ghost" onClick={onRetry}>
          Thử lại
        </button>
      )}
    </div>
  ) : null;
}
export function Empty({
  title,
  children,
  icon = "book",
}: {
  title: string;
  children?: ReactNode;
  icon?: string;
}) {
  return (
    <div className="empty">
      <div className="empty-icon">
        <Icon name={icon} size={28} />
      </div>
      <h3>{title}</h3>
      <p>{children}</p>
    </div>
  );
}
export function Loading({ text = "Đang tải…" }: { text?: string }) {
  return (
    <div className="loading" role="status">
      <span className="spinner" />
      {text}
    </div>
  );
}
export const date = (value?: string) =>
  value
    ? new Date(value).toLocaleString("vi-VN", {
        day: "2-digit",
        month: "2-digit",
        year: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      })
    : "—";
export function JsonDetails({
  value,
  label = "Chi tiết kỹ thuật",
}: {
  value: unknown;
  label?: string;
}) {
  return (
    <details className="debug">
      <summary>{label}</summary>
      <pre>{JSON.stringify(value, null, 2)}</pre>
    </details>
  );
}
export function Markdown({ children }: { children: string }) {
  return (
    <div className="markdown">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: ({ children }) => <span>{children}</span>,
          img: ({ alt }) => (
            <span className="muted">
              [Ảnh: {alt || "không hiển thị trong câu trả lời"}]
            </span>
          ),
        }}
      >
        {children}
      </ReactMarkdown>
    </div>
  );
}
export function Modal({
  title,
  children,
  onClose,
  wide = false,
}: {
  title: string;
  children: ReactNode;
  onClose: () => void;
  wide?: boolean;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const node = dialog.current;
    node?.showModal();
    return () => node?.close();
  }, []);
  return (
    <dialog
      ref={dialog}
      className={wide ? "modal wide" : "modal"}
      onCancel={onClose}
    >
      <header>
        <h2>{title}</h2>
        <button className="icon-button" onClick={onClose} aria-label="Đóng">
          <Icon name="close" />
        </button>
      </header>
      {children}
    </dialog>
  );
}
export function ScopeEmpty() {
  return (
    <Empty title="Chọn môn học để bắt đầu">
      Chọn một môn ở thanh bên hoặc tạo môn học mới. Tài liệu và hội thoại được
      tách riêng theo từng môn.
    </Empty>
  );
}
export function PdfViewer({
  subjectId,
  documentId,
  versionId,
  name,
  page = 1,
  onClose,
}: {
  subjectId: string;
  documentId: string;
  versionId?: string;
  name: string;
  page?: number;
  onClose: () => void;
}) {
  const url = `/api/subjects/${encodeURIComponent(subjectId)}/documents/${encodeURIComponent(documentId)}/pdf${versionId ? `?version_id=${encodeURIComponent(versionId)}` : ""}#page=${page}`;
  return (
    <Modal title={name} onClose={onClose} wide>
      <div className="pdf-meta">
        <span>Trang PDF {page} · Trang vật lý, bắt đầu từ 1</span>
        <a href={url} target="_blank" rel="noreferrer">
          Mở PDF trong tab mới ↗
        </a>
      </div>
      <iframe
        title={`${name} — trang ${page}`}
        src={url}
        className="pdf-frame"
      />
      <p className="muted small-text">
        Nếu trình duyệt không hiển thị PDF tại đây, chọn “Mở PDF trong tab mới”.
      </p>
    </Modal>
  );
}
export function Progress({
  progress,
}: {
  progress: Record<string, unknown> | undefined;
}) {
  if (!progress || Object.keys(progress).length === 0) return null;
  const labels: Record<string, string> = {
    pages: "Trang",
    pages_done: "Trang đã đọc",
    pages_processed: "Trang đã đọc",
    total_pages: "Tổng trang",
    chunks: "Chunks",
    chunks_done: "Chunks đã xử lý",
    chunks_embedded: "Chunks đã lập chỉ mục",
    total_chunks: "Tổng chunks",
    batches_done: "Batch hoàn tất",
    completed: "Đã hoàn tất",
    total: "Tổng",
    stage: "Giai đoạn",
    questions_done: "Câu đã chạy",
    processed_pages: "Trang đã xử lý",
    text_pages: "Trang có text",
  };
  return (
    <div className="progress-facts">
      {Object.entries(progress)
        .filter(([, v]) => typeof v === "number" || typeof v === "string")
        .map(([k, v]) => (
          <span key={k}>
            {labels[k] || k}: <strong>{String(v)}</strong>
          </span>
        ))}
    </div>
  );
}
