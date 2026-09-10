import { useCallback, useEffect, useRef, useState } from "react";
import type { FormEvent, KeyboardEvent } from "react";
import { api, errorText, post } from "./api";
import type {
  Answer,
  Citation,
  Config,
  Conversation,
  Doc,
  Message,
  Subject,
} from "./types";
import {
  Empty,
  ErrorBox,
  Icon,
  JsonDetails,
  Loading,
  Markdown,
  PdfViewer,
} from "./Common";

export default function Chat({
  subject,
  config,
}: {
  subject: Subject;
  config: Config | null;
}) {
  const [conversations, setConversations] = useState<Conversation[]>([]),
    [conversation, setConversation] = useState<string | null>(null),
    [messages, setMessages] = useState<Message[]>([]),
    [docs, setDocs] = useState<Doc[]>([]);
  const [question, setQuestion] = useState(""),
    [pending, setPending] = useState(""),
    [mode, setMode] = useState<"direct" | "assistant">("direct"),
    [retrieval, setRetrieval] = useState<"dense" | "lexical" | "hybrid">(
      config?.retrieval_mode || "lexical",
    );
  const [loading, setLoading] = useState(true),
    [historyLoading, setHistoryLoading] = useState(false),
    [busy, setBusy] = useState(false),
    [error, setError] = useState<string | null>(null),
    [viewer, setViewer] = useState<Citation | null>(null);
  const sequence = useRef(0),
    alive = useRef(true),
    bottom = useRef<HTMLDivElement>(null),
    input = useRef<HTMLTextAreaElement>(null);
  const loadBase = useCallback(async () => {
    const [c, d] = await Promise.all([
      api<Conversation[]>(`/subjects/${subject.id}/conversations`),
      api<Doc[]>(`/subjects/${subject.id}/documents`),
    ]);
    if (alive.current) {
      setConversations(c);
      setDocs(d);
    }
    return c;
  }, [subject.id]);
  async function loadHistory(id: string | null) {
    const seq = ++sequence.current;
    if (!id) {
      setMessages([]);
      setHistoryLoading(false);
      return;
    }
    setHistoryLoading(true);
    try {
      const result = await api<Message[]>(
        `/subjects/${subject.id}/conversations/${id}/messages`,
      );
      if (seq === sequence.current && alive.current) setMessages(result);
    } catch (e) {
      if (seq === sequence.current && alive.current) setError(errorText(e));
    } finally {
      if (seq === sequence.current && alive.current) setHistoryLoading(false);
    }
  }
  useEffect(() => {
    alive.current = true;
    loadBase()
      .then((c) => {
        if (!alive.current) return;
        const saved = localStorage.getItem(`skh.conversation.${subject.id}`);
        const id = c.some((x) => x.id === saved) ? saved : c[0]?.id || null;
        setConversation(id);
        void loadHistory(id);
      })
      .catch((e) => {
        if (alive.current) setError(errorText(e));
      })
      .finally(() => {
        if (alive.current) setLoading(false);
      });
    const timer = window.setInterval(() => {
      if (!document.hidden)
        api<Doc[]>(`/subjects/${subject.id}/documents`)
          .then((d) => {
            if (alive.current) setDocs(d);
          })
          .catch(() => {});
    }, 6000);
    return () => {
      alive.current = false;
      ++sequence.current;
      window.clearInterval(timer);
    };
  }, [loadBase, subject.id]);
  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "instant", block: "nearest" });
  }, [messages.length, pending]);
  function choose(id: string | null) {
    setConversation(id);
    setError(null);
    setQuestion("");
    if (id) localStorage.setItem(`skh.conversation.${subject.id}`, id);
    else localStorage.removeItem(`skh.conversation.${subject.id}`);
    void loadHistory(id);
  }
  const ready = docs.some((d) => d.active_version_id);
  async function send(e?: FormEvent) {
    e?.preventDefault();
    if (!question.trim() || busy || !ready || !config?.openai_configured)
      return;
    const text = question.trim();
    setBusy(true);
    setPending(text);
    setQuestion("");
    setError(null);
    try {
      const result = await post<Answer>(`/subjects/${subject.id}/chat`, {
        question: text,
        conversation_id: conversation,
        mode,
        retrieval_mode: retrieval,
      });
      if (!alive.current) return;
      setConversation(result.conversation_id);
      localStorage.setItem(
        `skh.conversation.${subject.id}`,
        result.conversation_id,
      );
      setMessages((prev) => [
        ...prev,
        {
          id: `submitted-${result.message_id}`,
          role: "user",
          content: text,
          citations: [],
          debug: {},
        },
        {
          id: result.message_id,
          role: "assistant",
          content: result.answer,
          citations: result.citations,
          debug: result.debug,
        },
      ]);
      await loadHistory(result.conversation_id);
      await loadBase().catch((e) => {
        if (alive.current)
          setError(
            "Câu trả lời đã lưu, nhưng chưa tải lại được danh sách hội thoại. " +
              errorText(e),
          );
      });
    } catch (e) {
      if (alive.current) {
        setQuestion(text);
        setError(errorText(e));
        if (conversation) await loadHistory(conversation);
      }
    } finally {
      if (alive.current) {
        setBusy(false);
        setPending("");
        input.current?.focus();
      }
    }
  }
  function keyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      void send();
    }
  }
  async function refresh() {
    setError(null);
    try {
      await loadBase();
      await loadHistory(conversation);
    } catch (e) {
      setError(errorText(e));
    }
  }
  return (
    <>
      <div className="section-heading">
        <div>
          <h2>
            Hỏi đáp trong môn <span>{subject.name}</span>
          </h2>
          <p className="muted">
            Chỉ dùng tài liệu của môn đang chọn. Kiểm tra nguồn trước khi sử
            dụng câu trả lời.
          </p>
        </div>
      </div>
      <div className="chat-toolbar">
        <label className="conversation-select">
          <span className="sr-only">Chọn hội thoại</span>
          <select
            aria-label="Chọn hội thoại"
            value={conversation || ""}
            disabled={busy || loading}
            onChange={(e) => choose(e.target.value || null)}
          >
            <option value="">Hội thoại mới</option>
            {conversations.map((c) => (
              <option value={c.id} key={c.id}>
                {c.title}
              </option>
            ))}
          </select>
        </label>
        <button
          className="small ghost"
          disabled={busy || historyLoading}
          onClick={() => choose(null)}
        >
          <Icon name="plus" size={16} />
          Hội thoại mới
        </button>
        <button
          className="small ghost"
          disabled={busy}
          onClick={refresh}
          title="Tải lại lịch sử"
        >
          <Icon name="refresh" size={16} />
          <span className="desktop-only">Tải lại</span>
        </button>
      </div>
      <div className="chat-panel">
        <div
          className="chat-messages"
          aria-live="polite"
          aria-busy={busy || historyLoading}
        >
          {loading || historyLoading ? (
            <Loading text="Đang tải hội thoại…" />
          ) : messages.length === 0 && !pending ? (
            <Empty
              title={
                ready
                  ? "Bạn muốn hiểu rõ điều gì?"
                  : "Môn học chưa có tài liệu sẵn sàng"
              }
              icon="chat"
            >
              {ready
                ? "Đặt câu hỏi cụ thể về PDF đã upload. Câu trả lời kèm thẻ nguồn để mở lại đúng trang."
                : "Upload PDF trong tab Tài liệu và đợi xử lý xong để bắt đầu hỏi đáp."}
            </Empty>
          ) : (
            messages.map((m) => (
              <article
                className={`message ${m.role === "user" ? "user-message" : "assistant-message"}`}
                key={m.id}
              >
                <div className="message-label">
                  {m.role === "user" ? "Bạn" : "Knowledge Hub"}
                </div>
                {m.role === "user" ? (
                  <div className="user-content">{m.content}</div>
                ) : (
                  <Markdown>{m.content}</Markdown>
                )}
                {m.role === "assistant" && m.citations?.length > 0 && (
                  <div className="citations">
                    <p className="sources-label">
                      <Icon name="link" size={14} />
                      NGUỒN TÀI LIỆU
                    </p>
                    {m.citations.map((c, i) => {
                      const state =
                        c.state ||
                        c.status ||
                        (c.is_deleted
                          ? "deleted"
                          : c.is_active === false
                            ? "replaced"
                            : "active");
                      return (
                        <button
                          key={`${c.version_id}-${c.id}-${i}`}
                          className={`source-card ${state === "deleted" ? "deleted" : ""}`}
                          onClick={() => setViewer(c)}
                          disabled={
                            state === "deleted" ||
                            (c.source_type || "pdf") !== "pdf"
                          }
                          title={
                            state === "deleted"
                              ? "Tài liệu đã bị xóa"
                              : (c.source_type || "pdf") !== "pdf"
                                ? "Nguồn full-text theo đoạn; không có trang PDF"
                                : `Mở ${c.document_name} tại trang ${c.page_start}`
                          }
                        >
                          <span className="source-number">[{c.id}]</span>
                          <div>
                            <strong>{c.document_name}</strong>
                            <span className="source-meta">
                              v{c.version} ·{" "}
                              {(c.source_type || "pdf") !== "pdf"
                                ? `Đoạn ${(c.paragraph_ids || []).join(", ")}`
                                : `Trang PDF ${c.page_start}${c.page_end !== c.page_start ? `–${c.page_end}` : ""}`}
                              {state === "replaced"
                                ? " · Phiên bản đã thay thế"
                                : state === "deleted"
                                  ? " · Nguồn đã xóa"
                                  : ""}
                            </span>
                            {(c.excerpt || c.text) && (
                              <p>{c.excerpt || c.text}</p>
                            )}
                          </div>
                          {state !== "deleted" &&
                            (c.source_type || "pdf") === "pdf" && (
                              <span aria-hidden="true">↗</span>
                            )}
                        </button>
                      );
                    })}
                  </div>
                )}
                {m.role === "assistant" &&
                  m.debug &&
                  Object.keys(m.debug).length > 0 && (
                    <JsonDetails
                      value={m.debug}
                      label="Tokens, thời gian, retrieval và tool trace"
                    />
                  )}
              </article>
            ))
          )}
          {pending && (
            <>
              <article className="message user-message pending-message">
                <div className="message-label">Bạn · Đang gửi</div>
                <div className="user-content">{pending}</div>
              </article>
              <Loading
                text={
                  mode === "assistant"
                    ? "Trợ lý đang xử lý yêu cầu và các công cụ…"
                    : "Đang tìm nguồn và tạo câu trả lời…"
                }
              />
            </>
          )}
          <div ref={bottom} />
        </div>
        <div className="composer">
          <ErrorBox error={error} />
          {error && (
            <p className="small-text muted">
              Câu hỏi được giữ lại. Nếu yêu cầu đã timeout, bấm “Tải lại” để
              kiểm tra lịch sử trước khi gửi lại.
            </p>
          )}
          <div className="composer-options">
            <div className="segmented" aria-label="Chế độ hỏi đáp">
              <button
                className={mode === "direct" ? "selected" : ""}
                disabled={busy}
                onClick={() => setMode("direct")}
              >
                Hỏi tài liệu
              </button>
              <button
                className={mode === "assistant" ? "selected" : ""}
                disabled={busy}
                onClick={() => setMode("assistant")}
              >
                Trợ lý tài liệu
              </button>
            </div>
            <details className="retrieval-options">
              <summary>Tìm kiếm: {retrieval}</summary>
              <label>
                Chế độ truy xuất
                <select
                  value={retrieval}
                  onChange={(e) =>
                    setRetrieval(e.target.value as typeof retrieval)
                  }
                  disabled={busy}
                >
                  <option value="lexical">Lexical · từ khóa</option>
                  <option value="dense">Dense · ngữ nghĩa</option>
                  <option value="hybrid">Hybrid · kết hợp RRF</option>
                </select>
              </label>
              <p>
                Mỗi chế độ dùng cùng giới hạn context. Có thể so sánh trong tab
                Đánh giá.
              </p>
            </details>
          </div>
          {mode === "assistant" && (
            <p className="mode-hint">
              Trợ lý có thể tìm tài liệu, đọc khoảng trang, liệt kê tài liệu và
              kiểm tra tác vụ. Tóm tắt dài cần xác nhận chủ động ở tab Tài liệu.
            </p>
          )}
          <form onSubmit={send} className="composer-input">
            <textarea
              ref={input}
              aria-label="Câu hỏi"
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              onKeyDown={keyDown}
              maxLength={10000}
              rows={3}
              disabled={busy || !ready || !config?.openai_configured}
              placeholder={
                !ready
                  ? "Cần ít nhất một tài liệu sẵn sàng…"
                  : !config?.openai_configured
                    ? "Cấu hình OpenAI API key để hỏi đáp…"
                    : `Hỏi về tài liệu môn ${subject.name}…`
              }
            />
            <button
              className="primary send-button"
              aria-label="Gửi câu hỏi"
              disabled={
                busy ||
                historyLoading ||
                !question.trim() ||
                !ready ||
                !config?.openai_configured
              }
            >
              <Icon name="arrow" size={20} />
              <span>{busy ? "Đang trả lời" : "Gửi"}</span>
            </button>
          </form>
          <div className="composer-footer">
            <span>Enter để gửi · Shift + Enter để xuống dòng</span>
            <span>
              {subject.name} · {docs.filter((d) => d.active_version_id).length}{" "}
              tài liệu sẵn sàng
            </span>
          </div>
        </div>
      </div>
      {viewer && (
        <PdfViewer
          subjectId={subject.id}
          documentId={viewer.document_id}
          versionId={viewer.version_id}
          name={`${viewer.document_name} · v${viewer.version}`}
          page={viewer.page_start}
          onClose={() => setViewer(null)}
        />
      )}
    </>
  );
}
