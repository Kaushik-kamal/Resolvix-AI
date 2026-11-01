import { Loader2, ShieldCheck } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Navigate, useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { isApiError } from "../../api/client";
import { useAuth } from "../../auth/AuthContext";
import { errorMessage } from "../../components";

export default function LoginPage() {
  const { status, login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const from = (location.state as { from?: string } | null)?.from ?? "/";
  // /login?expired=1 is where a 401 (REST or the stream's session probe) sends the user
  const [searchParams] = useSearchParams();
  const expired = searchParams.get("expired") === "1";
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (status === "authenticated") return <Navigate to={from} replace />;

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setPending(true);
    setError(null);
    try {
      await login(email.trim(), password);
      navigate(from, { replace: true });
    } catch (err) {
      setError(isApiError(err) && err.status === 401 ? "Invalid email or password." : errorMessage(err));
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="flex min-h-full items-center justify-center bg-bg p-4">
      <form onSubmit={onSubmit} className="card w-full max-w-sm p-6" aria-label="Sign in">
        <div className="mb-5 flex items-center gap-2 text-header">
          <ShieldCheck size={24} aria-hidden />
          <h1 className="text-lg font-semibold">Resolvix Ops</h1>
        </div>
        <label className="label" htmlFor="email">
          Email
        </label>
        <input
          id="email"
          name="email"
          type="text"
          autoComplete="username"
          className="input mb-3"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          required
          autoFocus
        />
        <label className="label" htmlFor="password">
          Password
        </label>
        <input
          id="password"
          name="password"
          type="password"
          autoComplete="current-password"
          className="input mb-4"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
        />
        {expired ? (
          <p
            role="status"
            data-testid="session-expired"
            className="mb-3 rounded border border-[#E8D3B1] bg-[#F5E9D8] px-3 py-2 text-xs text-[#80551F]"
          >
            Your session expired, please sign in again
          </p>
        ) : null}
        {error ? (
          <p role="alert" className="mb-3 rounded border border-[#EBC4B6] bg-[#F6E1D9] px-3 py-2 text-xs text-[#8D3C21]">
            {error}
          </p>
        ) : null}
        <button type="submit" className="btn btn-primary w-full" disabled={pending}>
          {pending ? <Loader2 size={16} className="animate-spin" aria-hidden /> : null}
          Sign in
        </button>
        <p className="mt-4 text-xs text-ink-faint">Demo users are listed in the ops README (seed users).</p>
      </form>
    </div>
  );
}
