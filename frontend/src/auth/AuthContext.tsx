import {
  type FormEvent,
  type ReactNode,
  useEffect,
  useRef,
  useState,
} from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";

import { ApiError, apiRequest } from "../api/client";
import { type Account, AuthContext, type AuthStatus, useAuth } from "./authState";

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AuthStatus>("loading");
  const [account, setAccount] = useState<Account | null>(null);
  const restored = useRef(false);

  useEffect(() => {
    if (restored.current) return;
    restored.current = true;
    void apiRequest<Account>("/auth/me")
      .then((current) => {
        setAccount(current);
        setStatus("authenticated");
      })
      .catch(() => {
        setAccount(null);
        setStatus("anonymous");
      });
  }, []);

  async function login(email: string, password: string) {
    const current = await apiRequest<Account>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    });
    setAccount(current);
    setStatus("authenticated");
  }

  async function logout() {
    try {
      await apiRequest<void>("/auth/logout", { method: "POST" });
    } finally {
      setAccount(null);
      setStatus("anonymous");
    }
  }

  return (
    <AuthContext.Provider value={{ status, account, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function ProtectedRoute({ children }: { children: ReactNode }) {
  const auth = useAuth();
  const location = useLocation();
  if (auth.status === "loading") {
    return (
      <main className="shell compact-shell" aria-live="polite">
        <p className="eyebrow">SESSION</p>
        <h1 className="page-title">正在恢复登录状态</h1>
      </main>
    );
  }
  if (auth.status === "anonymous") {
    return (
      <Navigate
        to="/login"
        replace
        state={{ from: location.pathname, sessionExpired: true }}
      />
    );
  }
  return children;
}

export function LoginPage() {
  const auth = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const routeState = location.state as
    | { from?: string; sessionExpired?: boolean }
    | null;
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  if (auth.status === "authenticated") {
    return <Navigate to={routeState?.from ?? "/reports"} replace />;
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setSubmitting(true);
    const form = new FormData(event.currentTarget);
    try {
      await auth.login(String(form.get("email")), String(form.get("password")));
      navigate(routeState?.from ?? "/reports", { replace: true });
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "登录失败，请稍后重试。");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="auth-layout">
      <section className="auth-intro">
        <p className="eyebrow">OPERATIONS INTELLIGENCE</p>
        <h1 className="page-title">登录运营策略工作台</h1>
        <p className="lead">继续查看已确认简报、生成进度与历史报告。</p>
      </section>
      <section className="auth-card" aria-labelledby="login-title">
        <h2 id="login-title">账号登录</h2>
        {routeState?.sessionExpired && (
          <p className="status-message" role="status">
            登录状态已失效，请重新登录。
          </p>
        )}
        <form onSubmit={submit}>
          <label>
            邮箱
            <input name="email" type="email" autoComplete="email" required />
          </label>
          <label>
            密码
            <input
              name="password"
              type="password"
              autoComplete="current-password"
              minLength={12}
              required
            />
          </label>
          {error && (
            <p className="error-message" role="alert">
              {error}
            </p>
          )}
          <button className="primary-button" type="submit" disabled={submitting}>
            {submitting ? "正在登录…" : "登录"}
          </button>
        </form>
      </section>
    </main>
  );
}
