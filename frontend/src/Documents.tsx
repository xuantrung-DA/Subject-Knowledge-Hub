import { useCallback, useEffect, useRef, useState } from "react";
import type { ChangeEvent, DragEvent } from "react";
import { api, errorText, post, upload } from "./api";
import type { Config, Doc, Job, Subject, Version } from "./types";
import {
  activeStatus,
  date,
  Empty,
  ErrorBox,
  Icon,
  JsonDetails,
  Loading,
  Markdown,
  Modal,
  PdfViewer,
  Progress,
  Status,
} from "./Common";

type UploadItem = {
  id: string;
  name: string;
  percent: number;
  status: "uploading" | "accepted" | "duplicate" | "failed";
  error?: string;
};
type SummaryResult = {
  requires_confirmation?: boolean;
  estimate?: Record<string, number | string | null>;
  job_id?: string;
  status?: string;
  cached?: boolean;
  summary?: string;
  page_start?: number;
  page_end?: number;
};

function JobDetails({
  job,
  subjectId,
  onClose,
}: {
  job: Job;
  subjectId: string;
  onClose: () => void;
}) {
  const [usage, setUsage] = useState<{
      totals: Record<string, number | null>;
      events: unknown[];
      pricing_updated_at?: string | null;
    } | null>(null),
    [error, setError] = useState<string | null>(null);
  const load = useCallback(async () => {
    setError(null);
    try {
      setUsage(
        await api(
          `/subjects/${subjectId}/usage?job_id=${encodeURIComponent(job.id)}`,
        ),
      );
    } catch (e) {
      setError(errorText(e));
    }
  }, [subjectId, job.id]);
  useEffect(() => {
    void load();
  }, [load]);
  return (
    <Modal title="Chi tiết xử lý và usage" onClose={onClose}>
      <Status status={job.status} />
      <p className="muted small-text">Job: {job.id}</p>
      <Progress progress={job.progress} />
      <ErrorBox error={error} onRetry={load} />
      {!usage && !error ? (
        <Loading />
      ) : (
        usage && (
          <>
            <div className="estimate">
              <strong>Usage thực đã ghi nhận cho tác vụ</strong>
              <dl>
                {Object.entries(usage.totals).map(([key, value]) => (
                  <div key={key}>
                    <dt>
                      {{
                        events_count: "Usage events",
                        calls: "Lượt gọi",
                        input_tokens: "Input tokens",
                        output_tokens: "Output tokens",
                        cached_tokens: "Cached tokens",
                        estimated_cost_usd: "Chi phí ước tính (USD)",
                      }[key] || key}
                    </dt>
                    <dd>
                      {value == null
                        ? "Chưa có giá"
                        : value.toLocaleString("vi-VN", {
                            maximumFractionDigits: 6,
                          })}
                    </dd>
                  </div>
                ))}
              </dl>
              <p className="small-text muted">
                Tổng được tính trên toàn bộ usage của job. Danh sách chi tiết
                giới hạn 100 events gần nhất; không cộng từ 100 events để thay
                tổng.
              </p>
            </div>
            <JsonDetails
              value={{ job, usage }}
              label="Checkpoints, kết quả và usage events"
            />
          </>
        )
      )}
    </Modal>
  );
}

function warningText(warning: unknown): string {
  if (!warning) return "";
  if (Array.isArray(warning))
    return warning
      .map((w) => (typeof w === "string" ? w : JSON.stringify(w)))
      .join(" · ");
  if (typeof warning === "string") return warning;
  return JSON.stringify(warning);
}

function SummaryModal({
  doc,
  subjectId,
  onClose,
  onChanged,
}: {
  doc: Doc;
  subjectId: string;
  onClose: () => void;
  onChanged: () => void;
}) {
  const version =
    doc.versions.find((v) => v.id === doc.active_version_id) ||
    doc.latest_version;
  const [start, setStart] = useState(1),
    [end, setEnd] = useState(version.page_count || 1),
    [busy, setBusy] = useState(false),
    [error, setError] = useState<string | null>(null),
    [result, setResult] = useState<SummaryResult | null>(null);
  async function request(confirmed: boolean) {
    setBusy(true);
    setError(null);
    try {
      const r = await post<SummaryResult>(
        `/subjects/${subjectId}/documents/${doc.id}/summary`,
        { page_start: start, page_end: end, confirmed },
      );
      setResult(r);
      if (r.job_id) onChanged();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <Modal title={`Tóm tắt · ${doc.name}`} onClose={onClose}>
      <p className="muted">
        Chọn phạm vi trang của phiên bản v{version.version}. Phạm vi ngắn bắt
        đầu xử lý ngay sau khi bấm tóm tắt. Phạm vi dài hiển thị ước tính và yêu
        cầu xác nhận thêm.
      </p>
      <div className="field-row">
        <label>
          Từ trang
          <input
            type="number"
            min={1}
            max={version.page_count || 1}
            value={start}
            onChange={(e) => {
              setStart(Number(e.target.value));
              setResult(null);
            }}
          />
        </label>
        <label>
          Đến trang
          <input
            type="number"
            min={start}
            max={version.page_count || 1}
            value={end}
            onChange={(e) => {
              setEnd(Number(e.target.value));
              setResult(null);
            }}
          />
        </label>
      </div>
      <ErrorBox error={error} />
      {result?.estimate && (
        <div className="estimate">
          <strong>Ước tính trước khi chạy</strong>
          <dl>
            {Object.entries(result.estimate).map(([k, v]) => (
              <div key={k}>
                <dt>
                  {{
                    pages: "Số trang",
                    input_tokens: "Input tokens ước tính",
                    estimated_calls: "Số lượt gọi ước tính",
                    token_budget: "Giới hạn tokens",
                    call_budget: "Giới hạn lượt gọi",
                  }[k] || k}
                </dt>
                <dd>
                  {typeof v === "number"
                    ? v.toLocaleString("vi-VN")
                    : (v ?? "Chưa cấu hình")}
                </dd>
              </div>
            ))}
          </dl>
          <p className="small-text muted">
            Tokens đầu vào và số lượt gọi là ước tính, usage thực được ghi khi
            chạy. Không có giá USD nếu chưa cấu hình bảng giá.
          </p>
        </div>
      )}
      {result?.summary && (
        <div className="summary-output">
          <span className="badge good">
            {result.cached ? "Đã có trong cache" : "Hoàn tất"}
          </span>
          <Markdown>{result.summary}</Markdown>
        </div>
      )}
      {result?.job_id && (
        <div className="notice success">
          Đã tạo tác vụ. Theo dõi tiến độ và xem kết quả ở khu vực “Tác vụ tóm
          tắt” trong tab Tài liệu.<code>{result.job_id}</code>
        </div>
      )}
      <div className="modal-actions">
        <button className="ghost" onClick={onClose}>
          Đóng
        </button>
        {!result?.job_id && !result?.summary && (
          <button
            className="primary"
            disabled={
              busy ||
              start < 1 ||
              end < start ||
              end > (version.page_count || 1)
            }
            onClick={() => request(!!result?.requires_confirmation)}
          >
            {busy
              ? "Đang xử lý…"
              : result?.requires_confirmation
                ? "Xác nhận bắt đầu tóm tắt"
                : "Tóm tắt phạm vi đã chọn"}
          </button>
        )}
      </div>
    </Modal>
  );
}

export default function Documents({
  subject,
  config,
}: {
  subject: Subject;
  config: Config | null;
}) {
  const [docs, setDocs] = useState<Doc[]>([]),
    [jobs, setJobs] = useState<Job[]>([]),
    [loading, setLoading] = useState(true),
    [error, setError] = useState<string | null>(null),
    [busy, setBusy] = useState<string | null>(null);
  const [uploads, setUploads] = useState<UploadItem[]>([]),
    [drag, setDrag] = useState(false),
    [uploading, setUploading] = useState(false),
    [viewer, setViewer] = useState<{ doc: Doc; version: Version } | null>(null),
    [versions, setVersions] = useState<Doc | null>(null),
    [summary, setSummary] = useState<Doc | null>(null),
    [jobDetails, setJobDetails] = useState<Job | null>(null);
  const input = useRef<HTMLInputElement>(null),
    replacement = useRef<HTMLInputElement>(null),
    replaceTarget = useRef<Doc | null>(null),
    alive = useRef(true),
    inflight = useRef(false);
  const load = useCallback(async () => {
    if (inflight.current) return;
    inflight.current = true;
    try {
      const [d, j] = await Promise.all([
        api<Doc[]>(`/subjects/${subject.id}/documents`),
        api<Job[]>(`/subjects/${subject.id}/jobs`),
      ]);
      if (alive.current) {
        setDocs(d);
        setJobs(j);
        setError(null);
      }
    } catch (e) {
      if (alive.current) setError(errorText(e));
    } finally {
      inflight.current = false;
      if (alive.current) setLoading(false);
    }
  }, [subject.id]);
  useEffect(() => {
    alive.current = true;
    void load();
    const id = window.setInterval(() => {
      if (document.visibilityState === "visible") void load();
    }, 4000);
    return () => {
      alive.current = false;
      window.clearInterval(id);
    };
  }, [load]);
  async function sendFiles(files: File[], replace?: Doc) {
    if (uploading || !config) return;
    setUploading(true);
    setError(null);
    for (const file of files) {
      const id = crypto.randomUUID();
      const entry: UploadItem = {
        id,
        name: file.name,
        percent: 0,
        status: "uploading",
      };
      setUploads((prev) => [...prev, entry]);
      const update = (patch: Partial<UploadItem>) => {
        if (alive.current)
          setUploads((prev) =>
            prev.map((u) => (u.id === id ? { ...u, ...patch } : u)),
          );
      };
      try {
        if (!file.name.toLowerCase().endsWith(".pdf"))
          throw new Error("Chỉ chấp nhận tệp PDF (.pdf).");
        if (file.size === 0)
          throw new Error("Tệp rỗng. Vui lòng chọn PDF có nội dung.");
        if (file.size > config.max_upload_mb * 1024 * 1024)
          throw new Error(`Tệp vượt giới hạn ${config.max_upload_mb} MB.`);
        const form = new FormData();
        form.append("file", file);
        const result = await upload<{ duplicate: boolean }>(
          `/subjects/${subject.id}/documents${replace ? `/${replace.id}/versions` : ""}`,
          form,
          (p) => update({ percent: p }),
        );
        update({
          percent: 100,
          status: result.duplicate ? "duplicate" : "accepted",
        });
        await load();
      } catch (e) {
        update({ status: "failed", error: errorText(e) });
      }
    }
    if (alive.current) setUploading(false);
  }
  function selected(e: ChangeEvent<HTMLInputElement>, replace = false) {
    const files = Array.from(e.target.files || []);
    if (files.length)
      void sendFiles(
        files,
        replace ? replaceTarget.current || undefined : undefined,
      );
    e.target.value = "";
  }
  function dropped(e: DragEvent) {
    e.preventDefault();
    setDrag(false);
    if (!uploading && config) void sendFiles(Array.from(e.dataTransfer.files));
  }
  async function remove(doc: Doc) {
    if (
      !window.confirm(
        `Xóa “${doc.name}” và tất cả phiên bản? Tài liệu bị loại khỏi tìm kiếm ngay. Lịch sử vẫn có thể ghi nhãn nguồn đã xóa.`,
      )
    )
      return;
    setBusy(doc.id);
    try {
      await api(`/subjects/${subject.id}/documents/${doc.id}`, {
        method: "DELETE",
      });
      await load();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(null);
    }
  }
  async function retry(job: Job) {
    setBusy(job.document_id || job.id);
    try {
      await post(`/subjects/${subject.id}/jobs/${job.id}/retry`);
      await load();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(null);
    }
  }
  const ready = docs.filter((d) => d.active_version_id).length,
    processing = docs.filter((d) =>
      activeStatus(d.latest_version.status),
    ).length;
  return (
    <>
      <div className="section-heading">
        <div>
          <h2>
            Tài liệu của môn <span>{subject.name}</span>
          </h2>
          <p className="muted">
            {docs.length} tài liệu · {ready} sẵn sàng
            {processing > 0 ? ` · ${processing} đang xử lý` : ""}
          </p>
        </div>
        <button
          className="ghost small"
          onClick={load}
          aria-label="Tải lại tài liệu"
        >
          <Icon name="refresh" size={16} />
          Tải lại
        </button>
      </div>
      <div
        className={`upload-zone ${drag ? "dragging" : ""} ${uploading ? "uploading" : ""}`}
        onDragOver={(e) => {
          e.preventDefault();
          if (!uploading) setDrag(true);
        }}
        onDragLeave={() => setDrag(false)}
        onDrop={dropped}
      >
        <div className="upload-symbol">
          <Icon name="upload" size={26} />
        </div>
        <div>
          <h3>
            {uploading
              ? "Đang gửi tệp lên máy chủ…"
              : "Thêm tài liệu vào môn học"}
          </h3>
          <p>Kéo thả PDF vào đây hoặc chọn nhiều tệp cùng lúc.</p>
          <span className="small-text">
            PDF có text Việt/Anh ·{" "}
            {config
              ? `Tối đa ${config.max_upload_mb} MB/tệp, ${config.max_pdf_pages.toLocaleString("vi-VN")} trang`
              : "Đang tải giới hạn upload…"}{" "}
            · PDF scan cần OCR ngoài ứng dụng
          </span>
        </div>
        <button
          className="primary"
          disabled={uploading || !config}
          onClick={() => input.current?.click()}
        >
          <Icon name="plus" size={18} />
          Chọn PDF
        </button>
        <input
          ref={input}
          type="file"
          multiple
          accept=".pdf,application/pdf"
          hidden
          onChange={(e) => selected(e)}
        />
        <input
          ref={replacement}
          type="file"
          accept=".pdf,application/pdf"
          hidden
          onChange={(e) => selected(e, true)}
        />
      </div>
      {uploads.length > 0 && (
        <section className="upload-list" aria-label="Tiến độ upload">
          <div className="inline-between">
            <strong>Truyền tệp</strong>
            {!uploading && (
              <button
                className="text-button small-text"
                onClick={() => setUploads([])}
              >
                Ẩn thông báo
              </button>
            )}
          </div>
          {uploads.map((u) => (
            <div className="upload-item" key={u.id}>
              <div className="inline-between">
                <span>{u.name}</span>
                <span className={u.status === "failed" ? "danger" : ""}>
                  {u.status === "uploading"
                    ? `${u.percent}% ${u.percent === 100 ? "· Đang chờ máy chủ xác nhận" : ""}`
                    : u.status === "accepted"
                      ? "Đã nhận · xem trạng thái xử lý bên dưới"
                      : u.status === "duplicate"
                        ? "Tệp trùng · sử dụng tài liệu đã có"
                        : "Upload thất bại"}
                </span>
              </div>
              {u.status === "uploading" && (
                <progress
                  value={u.percent}
                  max={100}
                  aria-label={`Upload ${u.name}`}
                />
              )}{" "}
              {u.error && <p className="danger small-text">{u.error}</p>}
            </div>
          ))}
        </section>
      )}
      <ErrorBox error={error} onRetry={load} />
      {loading ? (
        <Loading text="Đang tải tài liệu và trạng thái tác vụ…" />
      ) : docs.length === 0 ? (
        <Empty title="Tài liệu đầu tiên, kiến thức đầu tiên" icon="file">
          Upload PDF có text vào môn {subject.name}. Khi trạng thái chuyển “Sẵn
          sàng”, bạn có thể bắt đầu hỏi đáp.
        </Empty>
      ) : (
        <div className="document-list">
          {docs.map((doc) => {
            const v = doc.latest_version;
            const active = doc.versions.find(
              (x) => x.id === doc.active_version_id,
            );
            return (
              <article className="document-card" key={doc.id}>
                <div className="document-main">
                  <div className="file-icon">
                    <Icon name="file" size={25} />
                    <span>PDF</span>
                  </div>
                  <div className="document-info">
                    <h3>{doc.name}</h3>
                    <p className="document-meta">
                      {date(doc.created_at)}
                      <span>v{v.version}</span>
                      <span>
                        {(doc.source_type || "pdf") !== "pdf"
                          ? "Full-text · evidence theo đoạn"
                          : `${v.page_count ?? "—"} trang`}
                      </span>
                      <span>{v.chunk_count ?? "—"} chunks</span>
                      {v.text_page_count != null && (
                        <span>{v.text_page_count} trang có text</span>
                      )}
                    </p>
                    {doc.document_key && (
                      <p className="small-text muted">
                        Document key: {doc.document_key}
                      </p>
                    )}
                  </div>
                  <Status status={v.status} />
                </div>
                {active && active.id !== v.id && (
                  <p className="notice compact">
                    Hỏi đáp đang dùng v{active.version}. Phiên bản mới chỉ thay
                    thế khi xử lý hoàn tất.
                  </p>
                )}
                {activeStatus(v.status) && (
                  <Progress progress={doc.job?.progress} />
                )}{" "}
                {warningText(v.warning) && (
                  <p className="document-warning">{warningText(v.warning)}</p>
                )}
                {v.error_message && (
                  <div className="notice error compact">
                    <span>
                      {v.error_message}
                      {v.error_code && <small> · {v.error_code}</small>}
                    </span>
                  </div>
                )}
                <div className="document-actions">
                  <button
                    className="small ghost"
                    disabled={(doc.source_type || "pdf") !== "pdf"}
                    onClick={() => setViewer({ doc, version: active || v })}
                  >
                    Xem PDF
                  </button>
                  <button
                    className="small ghost"
                    onClick={() => setVersions(doc)}
                  >
                    Phiên bản ({doc.versions.length})
                  </button>
                  <button
                    className="small ghost"
                    disabled={
                      !active ||
                      (doc.source_type || "pdf") !== "pdf" ||
                      busy === doc.id
                    }
                    onClick={() => setSummary(doc)}
                  >
                    Tóm tắt
                  </button>
                  {doc.job &&
                    ["failed", "needs_ocr"].includes(doc.job.status) && (
                      <button
                        className="small ghost"
                        disabled={busy === doc.id}
                        onClick={() => retry(doc.job!)}
                      >
                        Thử lại xử lý
                      </button>
                    )}
                  {doc.job && (
                    <button
                      className="small ghost"
                      onClick={() => setJobDetails(doc.job!)}
                    >
                      Chi tiết xử lý
                    </button>
                  )}
                  <div className="action-spacer" />
                  <button
                    className="small ghost"
                    disabled={
                      uploading ||
                      (doc.source_type || "pdf") !== "pdf" ||
                      busy === doc.id
                    }
                    onClick={() => {
                      replaceTarget.current = doc;
                      replacement.current?.click();
                    }}
                  >
                    Thay PDF
                  </button>
                  <button
                    className="small ghost danger"
                    disabled={busy === doc.id}
                    onClick={() => remove(doc)}
                  >
                    Xóa
                  </button>
                </div>
              </article>
            );
          })}
        </div>
      )}
      {jobs.some((j) => j.kind === "summary") && (
        <section className="summary-jobs">
          <div className="section-heading">
            <div>
              <h2>Tác vụ tóm tắt</h2>
              <p className="muted">
                Tiến độ được lưu trên máy chủ và cập nhật khi mở lại trang.
              </p>
            </div>
          </div>
          {jobs
            .filter((j) => j.kind === "summary")
            .map((j) => (
              <article key={j.id} className="document-card">
                <div className="inline-between">
                  <strong>
                    {j.source?.document_name ||
                      docs.find((d) => d.id === j.document_id)?.name ||
                      "Tóm tắt tài liệu"}
                  </strong>
                  <Status status={j.status} />
                </div>
                {j.source && (
                  <p className="small-text muted">
                    Phiên bản {j.source.version ?? "—"} · Trang{" "}
                    {j.source.page_start ?? "—"}–{j.source.page_end ?? "—"}
                  </p>
                )}
                {j.source && j.source.state !== "active" && (
                  <p className="notice warning compact">
                    {j.source.state === "deleted"
                      ? "Tài liệu nguồn đã xóa. Đây là bản tóm tắt lưu trong lịch sử."
                      : "Tài liệu đã có phiên bản mới. Bản tóm tắt này thuộc phiên bản cũ."}
                  </p>
                )}
                <Progress progress={j.progress} />
                {j.error_message && <p className="danger">{j.error_message}</p>}
                {j.status === "ready" && (
                  <details className="summary-result">
                    <summary>Xem nội dung tóm tắt</summary>
                    <Markdown>
                      {String(
                        j.result?.summary ||
                          j.result?.content ||
                          "Kết quả không chứa văn bản tóm tắt.",
                      )}
                    </Markdown>
                  </details>
                )}
                {j.status === "failed" && j.source?.state === "active" && (
                  <button
                    className="small ghost"
                    disabled={busy === j.document_id || busy === j.id}
                    onClick={() => retry(j)}
                  >
                    Thử lại tác vụ
                  </button>
                )}
                <JsonDetails
                  value={{
                    id: j.id,
                    progress: j.progress,
                    result: j.result,
                    error_code: j.error_code,
                  }}
                  label="Phạm vi, usage và chi tiết tác vụ"
                />
              </article>
            ))}
        </section>
      )}
      {jobDetails && (
        <JobDetails
          job={jobDetails}
          subjectId={subject.id}
          onClose={() => setJobDetails(null)}
        />
      )}{" "}
      {viewer && (
        <PdfViewer
          subjectId={subject.id}
          documentId={viewer.doc.id}
          versionId={viewer.version.id}
          name={`${viewer.doc.name} · v${viewer.version.version}`}
          onClose={() => setViewer(null)}
        />
      )}{" "}
      {versions && (
        <Modal
          title={`Phiên bản · ${versions.name}`}
          onClose={() => setVersions(null)}
        >
          {versions.versions.map((v) => (
            <div className="version-row" key={v.id}>
              <div>
                <strong>Phiên bản {v.version}</strong>
                {v.id === versions.active_version_id && (
                  <span className="badge good">Đang dùng để hỏi đáp</span>
                )}
                <p className="muted small-text">
                  {v.page_count ?? "—"} trang · {v.chunk_count ?? "—"} chunks ·{" "}
                  {date(v.created_at)}
                </p>
              </div>
              <Status status={v.status} />
              <button
                className="small ghost"
                disabled={(versions.source_type || "pdf") !== "pdf"}
                onClick={() => {
                  setViewer({ doc: versions, version: v });
                  setVersions(null);
                }}
              >
                Xem PDF
              </button>
            </div>
          ))}
        </Modal>
      )}
      {summary && (
        <SummaryModal
          doc={summary}
          subjectId={subject.id}
          onClose={() => setSummary(null)}
          onChanged={load}
        />
      )}
    </>
  );
}
