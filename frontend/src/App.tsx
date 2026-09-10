import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { api, errorText, post, setCsrf } from "./api";
import type { Auth, Config, Subject, User } from "./types";
import { ErrorBox, Icon, Loading, Modal, ScopeEmpty } from "./Common";
import Documents from "./Documents";
import Chat from "./Chat";
import Evaluations from "./Evaluations";

function Login({ onLogin }: { onLogin: (auth: Auth) => void }) {
  const [register, setRegister] = useState(false),
    [email, setEmail] = useState(""),
    [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false),
    [error, setError] = useState<string | null>(null);
  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      onLogin(
        await post<Auth>(`/auth/${register ? "register" : "login"}`, {
          email,
          password,
        }),
      );
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }
  return (
    <main className="auth-page">
      <section className="auth-intro">
        <div className="brand">
          <span className="brand-mark">
            <Icon size={27} />
          </span>
          <span>
            Subject
            <br />
            <strong>Knowledge Hub</strong>
          </span>
        </div>
        <div>
          <p className="eyebrow">KHÔNG GIAN HỌC TẬP CỦA BẠN</p>
          <h1>
            Từ tài liệu.
            <br />
            Đến hiểu biết.
          </h1>
          <p>
            Tập trung PDF theo môn học, đặt câu hỏi và quay lại đúng trang để
            kiểm chứng câu trả lời.
          </p>
        </div>
        <span className="auth-footer">
          PDF của bạn · Nguồn rõ ràng · Hội thoại theo môn
        </span>
      </section>
      <section className="auth-form">
        <div className="auth-card">
          <p className="eyebrow">CHÀO MỪNG</p>
          <h2>
            {register ? "Tạo không gian của bạn" : "Đăng nhập để tiếp tục"}
          </h2>
          <p className="muted">Tài khoản local, không cần xác nhận email.</p>
          <form onSubmit={submit}>
            <label>
              Email
              <input
                type="email"
                autoComplete="username"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="ban@example.com"
                maxLength={254}
              />
            </label>
            <label>
              Mật khẩu
              <input
                type="password"
                autoComplete={register ? "new-password" : "current-password"}
                required
                minLength={register ? 10 : 1}
                maxLength={128}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder={register ? "Ít nhất 10 ký tự" : "Nhập mật khẩu"}
              />
            </label>
            <ErrorBox error={error} />
            <button className="primary full" disabled={busy}>
              {busy ? "Đang xử lý…" : register ? "Tạo tài khoản" : "Đăng nhập"}
              <Icon name="arrow" />
            </button>
          </form>
          <p className="auth-switch">
            {register ? "Đã có tài khoản?" : "Lần đầu sử dụng?"}{" "}
            <button
              className="text-button"
              onClick={() => {
                setRegister(!register);
                setError(null);
              }}
            >
              {register ? "Đăng nhập" : "Tạo tài khoản"}
            </button>
          </p>
        </div>
      </section>
    </main>
  );
}

export default function App() {
  const [user, setUser] = useState<User | null>(null),
    [loading, setLoading] = useState(true),
    [config, setConfig] = useState<Config | null>(null),
    [configError, setConfigError] = useState<string | null>(null);
  const [subjects, setSubjects] = useState<Subject[]>([]),
    [selected, setSelected] = useState<string | null>(null),
    [tab, setTab] = useState("documents");
  const [error, setError] = useState<string | null>(null),
    [busy, setBusy] = useState(false),
    [subjectLoading, setSubjectLoading] = useState(false);
  const [editor, setEditor] = useState<{ id?: string; name: string } | null>(
      null,
    ),
    [menu, setMenu] = useState(false);
  const current = subjects.find((s) => s.id === selected);
  function authenticated(auth: Auth) {
    setCsrf(auth.csrf_token);
    setUser(auth.user);
    setSelected(localStorage.getItem(`skh.subject.${auth.user.id}`));
  }
  async function loadConfig() {
    setConfigError(null);
    try {
      setConfig(await api<Config>("/config"));
    } catch (e) {
      setConfigError(errorText(e));
    }
  }
  async function loadSubjects() {
    setSubjectLoading(true);
    try {
      setSubjects(await api<Subject[]>("/subjects"));
      setError(null);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setSubjectLoading(false);
    }
  }
  useEffect(() => {
    void loadConfig();
    api<Auth>("/auth/me")
      .then(authenticated)
      .catch(() => {})
      .finally(() => setLoading(false));
    const expired = () => {
      setUser(null);
      setCsrf("");
      setSubjects([]);
      setSelected(null);
    };
    window.addEventListener("session-expired", expired);
    return () => window.removeEventListener("session-expired", expired);
  }, []);
  useEffect(() => {
    if (user) void loadSubjects();
  }, [user]);
  function choose(id: string) {
    setSelected(id);
    setMenu(false);
    if (user) localStorage.setItem(`skh.subject.${user.id}`, id);
  }
  async function saveSubject(e: FormEvent) {
    e.preventDefault();
    if (!editor) return;
    setBusy(true);
    setError(null);
    try {
      const result = await api<Subject>(
        editor.id ? `/subjects/${editor.id}` : "/subjects",
        {
          method: editor.id ? "PATCH" : "POST",
          body: JSON.stringify({ name: editor.name.trim() }),
        },
      );
      await loadSubjects();
      choose(result.id);
      setEditor(null);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }
  async function deleteSubject() {
    if (
      !current ||
      !window.confirm(
        `Xóa môn “${current.name}” cùng tài liệu và hội thoại? Thao tác này không thể hoàn tác trong ứng dụng.`,
      )
    )
      return;
    setBusy(true);
    try {
      await api(`/subjects/${current.id}`, { method: "DELETE" });
      setSelected(null);
      if (user) localStorage.removeItem(`skh.subject.${user.id}`);
      await loadSubjects();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }
  async function logout() {
    setBusy(true);
    try {
      await post("/auth/logout");
      setUser(null);
      setCsrf("");
      setSubjects([]);
      setSelected(null);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }
  if (loading)
    return (
      <div className="boot">
        <Loading text="Đang mở không gian học tập…" />
      </div>
    );
  if (!user) return <Login onLogin={authenticated} />;
  return (
    <div className="app-shell">
      <aside className={`sidebar ${menu ? "open" : ""}`}>
        <div className="brand">
          <span className="brand-mark">
            <Icon size={25} />
          </span>
          <span>
            Subject
            <br />
            <strong>Knowledge Hub</strong>
          </span>
        </div>
        <div className="sidebar-heading">
          <span>MÔN HỌC</span>
          <button
            className="icon-button"
            title="Tạo môn học"
            aria-label="Tạo môn học"
            onClick={() => {
              setEditor({ name: "" });
              setError(null);
            }}
          >
            <Icon name="plus" size={18} />
          </button>
        </div>
        <nav className="subjects" aria-label="Môn học">
          {subjectLoading && subjects.length === 0 ? (
            <Loading />
          ) : (
            subjects.map((s) => (
              <button
                key={s.id}
                className={`subject ${s.id === selected ? "selected" : ""}`}
                onClick={() => choose(s.id)}
              >
                <Icon size={18} />
                <span>{s.name}</span>
                {s.id === selected && <span className="selected-dot" />}
              </button>
            ))
          )}
          {!subjectLoading && subjects.length === 0 && (
            <p className="sidebar-empty">
              Chưa có môn học.
              <br />
              Tạo môn đầu tiên để thêm PDF.
            </p>
          )}
        </nav>
        <button
          className="new-subject"
          onClick={() => {
            setEditor({ name: "" });
            setError(null);
          }}
        >
          <Icon name="plus" size={18} />
          Tạo môn học mới
        </button>
        <div className="sidebar-note">
          <Icon name="link" size={18} />
          <p>
            Câu trả lời gắn với nguồn.
            <br />
            Luôn kiểm tra trang được dẫn.
          </p>
        </div>
        <div className="account">
          <div className="avatar">{user.email[0].toUpperCase()}</div>
          <span title={user.email}>
            {user.email}
            <small>Tài khoản local</small>
          </span>
          <button
            className="icon-button"
            title="Đăng xuất"
            aria-label="Đăng xuất"
            disabled={busy}
            onClick={logout}
          >
            <Icon name="logout" size={18} />
          </button>
        </div>
      </aside>
      {menu && (
        <button
          className="sidebar-backdrop"
          aria-label="Đóng danh sách môn"
          onClick={() => setMenu(false)}
        />
      )}
      <main className="workspace">
        <header className="topbar">
          <div className="breadcrumbs">
            <button
              className="mobile-menu ghost small"
              onClick={() => setMenu(!menu)}
            >
              Môn học
            </button>
            <span>Không gian học tập</span>
            <span>/</span>
            <strong>{current?.name || "Chọn môn học"}</strong>
          </div>
          <a
            href="/api/docs"
            target="_blank"
            rel="noreferrer"
            className="api-docs"
          >
            API docs ↗
          </a>
        </header>
        <div className="workspace-content">
          <div className="page-title">
            <div>
              <p className="eyebrow">KHO KIẾN THỨC THEO MÔN</p>
              <h1>{current?.name || "Không gian học tập"}</h1>
              <p className="muted">
                Tổ chức tài liệu, tìm câu trả lời và kiểm chứng từng nguồn.
              </p>
            </div>
            {current && (
              <div className="subject-actions">
                <button
                  className="small ghost"
                  onClick={() => {
                    setEditor({ id: current.id, name: current.name });
                    setError(null);
                  }}
                >
                  Đổi tên
                </button>
                <button
                  className="small ghost danger"
                  disabled={busy}
                  onClick={deleteSubject}
                >
                  Xóa môn
                </button>
              </div>
            )}
          </div>
          <ErrorBox error={editor ? null : error} onRetry={loadSubjects} />
          <ErrorBox error={configError} onRetry={loadConfig} />
          {config && !config.openai_configured && (
            <div className="notice warning">
              <span>
                <strong>Chưa cấu hình OpenAI API key.</strong> Điền{" "}
                <code>OPENAI_API_KEY</code> trong <code>.env</code> và khởi động
                lại API/worker. Tài khoản và môn học vẫn sử dụng được.
              </span>
              <button className="ghost small" onClick={loadConfig}>
                Kiểm tra lại
              </button>
            </div>
          )}
          <div className="tabs" role="tablist" aria-label="Chức năng">
            {[
              { id: "documents", label: "Tài liệu", icon: "file" },
              { id: "chat", label: "Hỏi đáp", icon: "chat" },
              { id: "evaluations", label: "Đánh giá", icon: "chart" },
            ].map((t) => (
              <button
                key={t.id}
                id={`tab-${t.id}`}
                role="tab"
                aria-selected={tab === t.id}
                aria-controls={`panel-${t.id}`}
                onClick={() => setTab(t.id)}
                className={tab === t.id ? "active" : ""}
              >
                <Icon name={t.icon} size={18} />
                {t.label}
              </button>
            ))}
          </div>
          <section
            role="tabpanel"
            id={`panel-${tab}`}
            aria-labelledby={`tab-${tab}`}
            className="tab-content"
          >
            {!current ? (
              <ScopeEmpty />
            ) : tab === "documents" ? (
              <Documents key={current.id} subject={current} config={config} />
            ) : tab === "chat" ? (
              <Chat key={current.id} subject={current} config={config} />
            ) : (
              <Evaluations key={current.id} subject={current} config={config} />
            )}
          </section>
          <footer className="statusbar">
            <span>
              <i className={config ? "connected" : ""} />
              {config ? "Máy chủ đã kết nối" : "Chưa xác định kết nối"}
              {config && ` · ${config.chat_model}`}
            </span>
            <span>Trang trích dẫn = thứ tự trang trong PDF, bắt đầu từ 1</span>
          </footer>
        </div>
      </main>
      {editor && (
        <Modal
          title={editor.id ? "Đổi tên môn học" : "Tạo môn học"}
          onClose={() => !busy && setEditor(null)}
        >
          <form onSubmit={saveSubject}>
            <label>
              Tên môn học
              <input
                autoFocus
                required
                maxLength={120}
                value={editor.name}
                onChange={(e) => setEditor({ ...editor, name: e.target.value })}
                placeholder="Ví dụ: Học máy"
              />
            </label>
            <ErrorBox error={error} />
            <div className="modal-actions">
              <button
                type="button"
                className="ghost"
                disabled={busy}
                onClick={() => setEditor(null)}
              >
                Hủy
              </button>
              <button
                className="primary"
                disabled={busy || !editor.name.trim()}
              >
                {busy ? "Đang lưu…" : "Lưu môn học"}
              </button>
            </div>
          </form>
        </Modal>
      )}
    </div>
  );
}
