import { useCallback, useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { api, errorText, post, upload } from "./api";
import type { Config, Doc, EvalRun, Subject } from "./types";
import {
  activeStatus,
  date,
  Empty,
  ErrorBox,
  Icon,
  JsonDetails,
  Loading,
  Modal,
  Progress,
  Status,
} from "./Common";

function ImportEvaluation({
  subjectId,
  docs,
  config,
  onClose,
  onImported,
}: {
  subjectId: string;
  docs: Doc[];
  config: Config;
  onClose: () => void;
  onImported: (run: EvalRun) => void;
}) {
  const [file, setFile] = useState<File | null>(null),
    [name, setName] = useState(""),
    [keys, setKeys] = useState<string[]>([]),
    [mapping, setMapping] = useState<Record<string, string>>({}),
    [count, setCount] = useState(0),
    [busy, setBusy] = useState(false),
    [error, setError] = useState<string | null>(null),
    [percent, setPercent] = useState(0);
  const [modes, setModes] = useState(["lexical"]),
    [generate, setGenerate] = useState(false),
    [limit, setLimit] = useState(10),
    [tokens, setTokens] = useState(30000),
    [calls, setCalls] = useState(50),
    [topK, setTopK] = useState(config.retrieval_top_k);
  useEffect(() => {
    setTopK((value) => Math.min(value, config.retrieval_top_k));
  }, [config.retrieval_top_k]);
  async function readFile(selected: File | null) {
    setFile(null);
    setKeys([]);
    setMapping({});
    setCount(0);
    setError(null);
    if (!selected) return;
    try {
      if (selected.size > 10 * 1024 * 1024)
        throw new Error(
          "Dataset trên UI giới hạn 10 MB. Chọn subset nhỏ để đánh giá trước.",
        );
      const lines = (await selected.text())
        .split(/\r?\n/)
        .filter((x) => x.trim());
      if (!lines.length)
        throw new Error("Dataset rỗng. Cần ít nhất một câu hỏi JSONL.");
      const found = new Set<string>();
      const ids = new Set<string>();
      lines.forEach((line, i) => {
        let row: Record<string, unknown>;
        try {
          row = JSON.parse(line);
        } catch {
          throw new Error(`Dòng ${i + 1}: JSON không hợp lệ.`);
        }
        if (
          !row ||
          typeof row !== "object" ||
          typeof row.id !== "string" ||
          typeof row.question !== "string" ||
          typeof row.reference_answer !== "string" ||
          typeof row.answerable !== "boolean" ||
          !Array.isArray(row.evidence)
        )
          throw new Error(
            `Dòng ${i + 1}: cần id, question, reference_answer, answerable và evidence.`,
          );
        if (ids.has(row.id))
          throw new Error(`Dòng ${i + 1}: id “${row.id}” bị trùng.`);
        ids.add(row.id);
        for (const evidence of row.evidence) {
          if (typeof evidence?.document_key !== "string")
            throw new Error(`Dòng ${i + 1}: evidence thiếu document_key.`);
          found.add(evidence.document_key);
        }
        const metadata = row.metadata as Record<string, unknown> | undefined;
        if (typeof metadata?.target_document_key === "string")
          found.add(metadata.target_document_key);
      });
      const list = [...found].sort();
      setKeys(list);
      setCount(lines.length);
      setLimit(Math.min(10, lines.length));
      setFile(selected);
      setName(selected.name.replace(/\.jsonl$/i, ""));
      setMapping(
        Object.fromEntries(
          list.map((key) => [
            key,
            docs.find((d) => d.document_key === key)?.id || "",
          ]),
        ),
      );
    } catch (e) {
      setError(errorText(e));
    }
  }
  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      const mapped = Object.fromEntries(
        keys.map((key) => {
          const doc = docs.find((d) => d.id === mapping[key]);
          if (!doc?.active_version_id)
            throw new Error(`Chọn tài liệu sẵn sàng cho ${key}.`);
          return [
            key,
            { document_id: doc.id, version_id: doc.active_version_id },
          ];
        }),
      );
      const form = new FormData();
      form.append("file", file);
      form.append("name", name.trim() || file.name);
      form.append("mapping", JSON.stringify(mapped));
      form.append(
        "config",
        JSON.stringify({
          modes,
          generate_answers: generate,
          limit,
          top_k: topK,
          max_tokens: tokens,
          max_calls: calls,
        }),
      );
      onImported(
        await upload<EvalRun>(
          `/subjects/${subjectId}/evaluations`,
          form,
          setPercent,
        ),
      );
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <Modal
      title="Nhập bộ câu hỏi đánh giá"
      onClose={() => !busy && onClose()}
      wide
    >
      <form onSubmit={submit}>
        <p className="muted">
          Dataset chỉ phục vụ đánh giá, không được lập chỉ mục vào kho tài liệu.
          Đáp án chuẩn không gửi vào prompt trả lời.
        </p>
        <label>
          Tệp JSONL
          <input
            type="file"
            accept=".jsonl,application/jsonl,application/x-ndjson"
            disabled={busy}
            onChange={(e) => void readFile(e.target.files?.[0] || null)}
          />
        </label>
        <details className="dataset-example">
          <summary>Định dạng một dòng JSONL</summary>
          <pre>
            {
              '{"id":"q001","question":"Câu hỏi của bạn?","reference_answer":"Đáp án chuẩn","answerable":true,"evidence":[{"document_key":"chapter_1","page_start":3,"page_end":3}],"tags":["vi"]}'
            }
          </pre>
          <p className="small-text muted">
            Mỗi dòng là một câu hỏi. Với câu ngoài phạm vi: answerable=false,
            evidence=[]. Trang phải khớp PDF của bạn.
          </p>
        </details>
        {file && (
          <>
            <label>
              Tên lần đánh giá
              <input
                value={name}
                maxLength={120}
                required
                onChange={(e) => setName(e.target.value)}
              />
            </label>
            <p className="notice compact">
              {count} câu hỏi đã đọc · {keys.length} document keys cần ánh xạ
            </p>
            {keys.length > 0 && (
              <div className="mapping-fields">
                <h3>Ánh xạ nguồn chuẩn</h3>
                <p className="muted small-text">
                  Gắn từng key với tài liệu của môn hiện tại. Phiên bản active
                  được cố định tại lúc import.
                </p>
                {keys.map((key) => (
                  <label key={key}>
                    <code>{key}</code>
                    <select
                      required
                      value={mapping[key] || ""}
                      onChange={(e) =>
                        setMapping((prev) => ({
                          ...prev,
                          [key]: e.target.value,
                        }))
                      }
                    >
                      <option value="">Chọn tài liệu…</option>
                      {docs
                        .filter((d) => d.active_version_id)
                        .map((d) => (
                          <option value={d.id} key={d.id}>
                            {d.name} · v
                            {
                              d.versions.find(
                                (v) => v.id === d.active_version_id,
                              )?.version
                            }
                          </option>
                        ))}
                    </select>
                  </label>
                ))}
              </div>
            )}
            <fieldset>
              <legend>Chế độ cần so sánh</legend>
              <div className="checkbox-row">
                {["lexical", "dense", "hybrid"].map((m) => (
                  <label className="checkbox" key={m}>
                    <input
                      type="checkbox"
                      checked={modes.includes(m)}
                      onChange={(e) =>
                        setModes((prev) =>
                          e.target.checked
                            ? [...prev, m]
                            : prev.filter((x) => x !== m),
                        )
                      }
                    />
                    {m}
                  </label>
                ))}
              </div>
            </fieldset>
            <label className="checkbox">
              <input
                type="checkbox"
                checked={generate}
                onChange={(e) => setGenerate(e.target.checked)}
              />
              Sinh câu trả lời để chấm thêm đáp án và citations
            </label>
            <div className="field-row">
              <label>
                Số đoạn truy xuất (top-k)
                <input
                  type="number"
                  min={1}
                  max={config.retrieval_top_k}
                  value={topK}
                  onChange={(e) => setTopK(Number(e.target.value))}
                />
              </label>
              <label>
                Số câu tối đa
                <input
                  type="number"
                  min={1}
                  max={Math.min(count, 500)}
                  value={limit}
                  onChange={(e) => setLimit(Number(e.target.value))}
                />
              </label>
              <label>
                Giới hạn tokens
                <input
                  type="number"
                  min={100}
                  max={2000000}
                  value={tokens}
                  onChange={(e) => setTokens(Number(e.target.value))}
                />
              </label>
              <label>
                Giới hạn API calls
                <input
                  type="number"
                  min={1}
                  max={10000}
                  value={calls}
                  onChange={(e) => setCalls(Number(e.target.value))}
                />
              </label>
            </div>
            <p className="notice warning compact">
              Dense/hybrid dùng OpenAI embeddings; sinh câu trả lời gọi thêm
              model. Import chưa chạy đánh giá. Xác nhận chạy riêng trong danh
              sách sau khi import.
            </p>
          </>
        )}
        <ErrorBox error={error} />
        {busy && (
          <progress value={percent} max={100} aria-label="Upload dataset" />
        )}
        <div className="modal-actions">
          <button
            type="button"
            className="ghost"
            disabled={busy}
            onClick={onClose}
          >
            Hủy
          </button>
          <button
            className="primary"
            disabled={
              busy ||
              !file ||
              modes.length === 0 ||
              limit < 1 ||
              limit > Math.min(count, 500) ||
              tokens < 100 ||
              calls < 1 ||
              !Number.isInteger(topK) ||
              topK < 1 ||
              topK > config.retrieval_top_k ||
              keys.some((k) => !mapping[k])
            }
          >
            {busy ? `Đang nhập ${percent}%…` : "Nhập dataset"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

function Report({ run, subjectId }: { run: EvalRun; subjectId: string }) {
  const summary = run.report?.summary as
    | Record<string, Record<string, unknown>>
    | undefined;
  const format = (value: unknown) =>
    value === null || value === undefined
      ? "Chưa đo"
      : typeof value === "number"
        ? Number.isInteger(value)
          ? value.toLocaleString("vi-VN")
          : value.toFixed(4)
        : String(value);
  const columns: [string, string][] = [
    ["sample_size", "Số mẫu"],
    ["evidence_recall_at_k", "Evidence Recall@k"],
    ["mrr", "MRR"],
    ["answer_token_f1", "Answer token F1"],
    ["unanswerable_accuracy", "Ngoài phạm vi đúng"],
    ["citation_validity", "Citation hợp lệ"],
    ["latency_p50_ms", "Latency p50 (ms)"],
    ["latency_p95_ms", "Latency p95 (ms)"],
    ["total_input_tokens", "Input tokens"],
    ["total_output_tokens", "Output tokens"],
    ["total_cost_usd", "Chi phí ước tính USD"],
    ["errors", "Số lỗi"],
  ];
  return (
    <div className="evaluation-detail">
      <div className="section-heading">
        <div>
          <h2>{run.name}</h2>
          <p className="muted">
            {date(run.created_at)} ·{" "}
            {run.question_count ?? run.dataset?.length ?? "—"} câu hỏi
          </p>
        </div>
        <Status status={run.status} />
      </div>
      {run.job && (
        <>
          <Progress progress={run.job.progress} />
          {run.job.error_message && (
            <p className="notice error">{run.job.error_message}</p>
          )}
        </>
      )}
      {summary && Object.keys(summary).length > 0 ? (
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Metric</th>
                {Object.keys(summary).map((mode) => (
                  <th key={mode}>{mode}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {columns.map(([key, label]) => (
                <tr key={key}>
                  <th scope="row">{label}</th>
                  {Object.entries(summary).map(([mode, metrics]) => (
                    <td key={mode}>{format(metrics[key])}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="muted">
          {activeStatus(run.status)
            ? "Worker đang chạy. Báo cáo sẽ xuất hiện sau khi có kết quả."
            : "Chưa có metric để hiển thị. Xem trạng thái và chi tiết của lần chạy."}
        </p>
      )}
      <div className="export-row">
        <span>Xuất dữ liệu:</span>
        {["json", "csv", "md"].map((f) => (
          <a
            className="button ghost small"
            key={f}
            href={`/api/subjects/${subjectId}/evaluations/${run.id}/export?format=${f}`}
            download
          >
            {f.toUpperCase()} ↓
          </a>
        ))}
      </div>
      {Array.isArray(run.report?.limitations) && (
        <div className="notice compact">
          <ul>
            {run.report.limitations.map((l, i) => (
              <li key={i}>{String(l)}</li>
            ))}
          </ul>
        </div>
      )}
      <JsonDetails value={run.config} label="Cấu hình và ngân sách" />
      <JsonDetails
        value={{
          report: run.report,
          results: run.results,
          mapping: run.mapping,
          job: run.job,
        }}
        label="Báo cáo đầy đủ, lỗi từng câu và mẫu để review"
      />
    </div>
  );
}

export default function Evaluations({
  subject,
  config,
}: {
  subject: Subject;
  config: Config | null;
}) {
  const [runs, setRuns] = useState<EvalRun[]>([]),
    [docs, setDocs] = useState<Doc[]>([]),
    [loading, setLoading] = useState(true),
    [error, setError] = useState<string | null>(null),
    [importing, setImporting] = useState(false),
    [busy, setBusy] = useState<string | null>(null),
    [selected, setSelected] = useState<string | null>(null),
    [detail, setDetail] = useState<EvalRun | null>(null);
  const alive = useRef(true),
    detailSeq = useRef(0);
  const load = useCallback(async () => {
    try {
      const [r, d] = await Promise.all([
        api<EvalRun[]>(`/subjects/${subject.id}/evaluations`),
        api<Doc[]>(`/subjects/${subject.id}/documents`),
      ]);
      if (alive.current) {
        setRuns(r);
        setDocs(d);
      }
    } catch (e) {
      if (alive.current) setError(errorText(e));
    } finally {
      if (alive.current) setLoading(false);
    }
  }, [subject.id]);
  useEffect(() => {
    alive.current = true;
    void load();
    const timer = window.setInterval(() => {
      if (!document.hidden) void load();
    }, 5000);
    return () => {
      alive.current = false;
      window.clearInterval(timer);
    };
  }, [load]);
  useEffect(() => {
    if (!selected) {
      setDetail(null);
      return;
    }
    const seq = ++detailSeq.current;
    const fetchDetail = () =>
      api<EvalRun>(`/subjects/${subject.id}/evaluations/${selected}`)
        .then((r) => {
          if (alive.current && seq === detailSeq.current) setDetail(r);
        })
        .catch((e) => {
          if (alive.current && seq === detailSeq.current)
            setError(errorText(e));
        });
    setDetail(null);
    void fetchDetail();
    const timer = window.setInterval(() => {
      if (!document.hidden) void fetchDetail();
    }, 4000);
    return () => {
      ++detailSeq.current;
      window.clearInterval(timer);
    };
  }, [selected, subject.id]);
  async function run(item: EvalRun) {
    if (
      !window.confirm(
        `Chạy đánh giá “${item.name}” với cấu hình/ngân sách đã chọn? Dense/hybrid và sinh câu trả lời có thể phát sinh phí OpenAI.`,
      )
    )
      return;
    setBusy(item.id);
    setError(null);
    try {
      await post(`/subjects/${subject.id}/evaluations/${item.id}/run`);
      setSelected(item.id);
      await load();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(null);
    }
  }
  return (
    <>
      <div className="section-heading">
        <div>
          <h2>
            Đánh giá trong môn <span>{subject.name}</span>
          </h2>
          <p className="muted">
            Đo retrieval và câu trả lời trên bộ câu hỏi có nguồn chuẩn do bạn
            cung cấp.
          </p>
        </div>
        <button
          className="primary"
          disabled={!config}
          onClick={() => setImporting(true)}
        >
          <Icon name="upload" size={18} />
          Nhập JSONL
        </button>
      </div>
      <div className="evaluation-note">
        <Icon name="chart" size={22} />
        <p>
          <strong>Đo trên dữ liệu thật của môn học.</strong> Lexical, dense và
          hybrid sử dụng cùng pipeline với ứng dụng. Citation hợp lệ về trang
          chưa đồng nghĩa với việc hỗ trợ đúng nội dung câu trả lời; cần review
          mẫu.
        </p>
      </div>
      <ErrorBox
        error={error}
        onRetry={() => {
          setError(null);
          void load();
        }}
      />
      {loading ? (
        <Loading />
      ) : runs.length === 0 ? (
        <Empty title="Bắt đầu bằng một bộ câu hỏi nhỏ" icon="chart">
          Chuẩn bị file JSONL gồm câu hỏi, đáp án và trang nguồn. Import, ánh xạ
          tài liệu rồi chủ động chạy đánh giá có giới hạn.
        </Empty>
      ) : (
        <div className="evaluation-runs">
          {runs.map((r) => (
            <article
              className={`evaluation-row ${selected === r.id ? "selected" : ""}`}
              key={r.id}
            >
              <button className="run-title" onClick={() => setSelected(r.id)}>
                <strong>{r.name}</strong>
                <span>
                  {date(r.created_at)} ·{" "}
                  {r.question_count ?? r.dataset?.length ?? "—"} câu hỏi
                </span>
              </button>
              <Status status={r.status} />
              <button className="ghost small" onClick={() => setSelected(r.id)}>
                Xem kết quả
              </button>
              {r.status !== "ready" && (
                <button
                  className="primary small"
                  disabled={busy === r.id || activeStatus(r.status)}
                  onClick={() => run(r)}
                >
                  {busy === r.id
                    ? "Đang gửi…"
                    : activeStatus(r.status)
                      ? "Đang chạy"
                      : "Chạy đánh giá"}
                </button>
              )}
            </article>
          ))}
        </div>
      )}
      {selected &&
        (detail ? (
          <Report run={detail} subjectId={subject.id} />
        ) : (
          <Loading text="Đang tải báo cáo…" />
        ))}
      {importing && config && (
        <ImportEvaluation
          subjectId={subject.id}
          docs={docs}
          config={config}
          onClose={() => setImporting(false)}
          onImported={(r) => {
            setImporting(false);
            setSelected(r.id);
            void load();
          }}
        />
      )}
    </>
  );
}
