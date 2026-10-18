import { BellRing, ChartLine, Eye, EyeOff, Heart, Lock, Mail, Phone, User } from "lucide-react";
import { useRef, useState, type FormEvent, type InputHTMLAttributes, type ReactNode } from "react";
import { Navigate, useNavigate, useSearchParams } from "react-router";

import { api, ApiError, USE_MOCKS } from "@/api";
import { MOCK_OTP } from "@/api/mock";
import { useAuth } from "@/auth/AuthProvider";
import { Logo } from "@/components/layout/Logo";
import { Button } from "@/components/ui/Button";
import { useToast } from "@/components/ui/Toast";
import { cn } from "@/lib/cn";

type Tab = "email" | "phone";

const message = (e: unknown) => (e instanceof ApiError ? e.message : "Something went wrong. Please try again.");

/** Only allow same-site relative redirects (prevents open-redirect via ?next=). */
function safeNext(next: string | null): string {
  return next && next.startsWith("/") && !next.startsWith("//") ? next : "/";
}

export function LoginPage() {
  const { user, setUser } = useAuth();
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const toast = useToast();
  const [tab, setTab] = useState<Tab>("email");
  const next = safeNext(params.get("next"));

  if (user) return <Navigate to={next} replace />;

  const onSignedIn = (u: Parameters<typeof setUser>[0], welcome: string) => {
    setUser(u);
    toast({ tone: "success", title: welcome });
    navigate(next, { replace: true });
  };

  return (
    <div className="grid min-h-[calc(100dvh-4rem)] lg:grid-cols-2">
      {/* Brand panel */}
      <div className="relative isolate hidden overflow-hidden border-r border-ink-100 bg-linear-to-br from-brand-100 via-brand-50 to-surface p-12 lg:flex lg:flex-col lg:justify-between">
        <div className="bg-grid-light absolute inset-0 -z-10 [mask-image:radial-gradient(ellipse_at_bottom_left,black_20%,transparent_70%)]" />
        <div className="absolute -bottom-32 -left-32 -z-10 size-[480px] rounded-full bg-brand-200/50 blur-[110px]" />
        <Logo />
        <div className="max-w-md">
          <h2 className="font-display text-4xl leading-tight font-bold tracking-tight text-ink-900">
            Your personal <span className="text-gradient-brand">deal radar.</span>
          </h2>
          <ul className="mt-8 space-y-5">
            {[
              [Heart, "Wishlist", "Save products and watch every store's price in one place."],
              [BellRing, "Price-drop alerts", "Pick a target price. We'll tell you the moment it hits."],
              [ChartLine, "Price history", "Know if today's 'sale' is actually a good deal."],
            ].map(([Icon, title, body]) => {
              const I = Icon as typeof Heart;
              return (
                <li key={title as string} className="flex gap-4">
                  <span className="grid size-11 shrink-0 place-items-center rounded-2xl border border-brand-100 bg-white shadow-sm">
                    <I className="size-5 text-brand-500" />
                  </span>
                  <div>
                    <p className="font-semibold text-ink-900">{title as string}</p>
                    <p className="mt-0.5 text-sm text-ink-500">{body as string}</p>
                  </div>
                </li>
              );
            })}
          </ul>
        </div>
        <p className="text-xs text-ink-500">Searching and comparing is always free — no account needed.</p>
      </div>

      {/* Form panel */}
      <div className="flex items-center justify-center px-4 py-12 sm:px-6">
        <div className="w-full max-w-md">
          <div className="rounded-[2rem] border border-ink-100 bg-white p-6 shadow-lift sm:p-8">
            <div className="grid grid-cols-2 rounded-xl bg-ink-100 p-1" role="tablist">
              {(
                [
                  ["email", "Email", Mail],
                  ["phone", "Mobile OTP", Phone],
                ] as const
              ).map(([value, label, Icon]) => (
                <button
                  key={value}
                  role="tab"
                  aria-selected={tab === value}
                  onClick={() => setTab(value)}
                  className={cn(
                    "inline-flex items-center justify-center gap-2 rounded-lg py-2 text-sm font-semibold transition",
                    tab === value ? "bg-white text-ink-900 shadow-sm" : "text-ink-500 hover:text-ink-800",
                  )}
                >
                  <Icon className="size-4" /> {label}
                </button>
              ))}
            </div>

            <div className="mt-6">
              {tab === "email" ? (
                <EmailForm initialMode={params.get("mode") === "signup" ? "signup" : "login"} onSignedIn={onSignedIn} />
              ) : (
                <PhoneForm onSignedIn={onSignedIn} />
              )}
            </div>

            <div className="my-6 flex items-center gap-3 text-xs text-ink-400">
              <span className="h-px flex-1 bg-ink-100" /> or <span className="h-px flex-1 bg-ink-100" />
            </div>

            <a
              href={api.auth.googleLoginUrl()}
              onClick={(e) => {
                if (USE_MOCKS) {
                  e.preventDefault();
                  toast({ tone: "error", title: "Google sign-in needs the backend", body: "Set VITE_USE_MOCKS=false once auth is live." });
                }
              }}
              className="flex h-12 w-full items-center justify-center gap-3 rounded-xl border border-ink-200 bg-white text-sm font-semibold text-ink-800 transition hover:bg-ink-100/60"
            >
              <GoogleIcon /> Continue with Google
            </a>
          </div>
          <p className="mt-6 text-center text-xs leading-5 text-ink-400">
            By continuing you agree to ShopSync's Terms and Privacy Policy.
          </p>
        </div>
      </div>
    </div>
  );
}

function EmailForm({
  initialMode,
  onSignedIn,
}: {
  initialMode: "login" | "signup";
  onSignedIn: (u: Awaited<ReturnType<typeof api.auth.login>>, welcome: string) => void;
}) {
  const [mode, setMode] = useState(initialMode);
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const signup = mode === "signup";

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (signup && password.length < 8) return setError("Password must be at least 8 characters.");
    setLoading(true);
    try {
      const user = signup ? await api.auth.signup(name.trim(), email.trim(), password) : await api.auth.login(email.trim(), password);
      onSignedIn(user, signup ? "Welcome to ShopSync!" : "Welcome back!");
    } catch (err) {
      setError(message(err));
    } finally {
      setLoading(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-4">
      <div>
        <h1 className="font-display text-2xl font-bold">{signup ? "Create your account" : "Sign in"}</h1>
        <p className="mt-1 text-sm text-ink-500">
          {signup ? "Already have an account?" : "New to ShopSync?"}{" "}
          <button type="button" onClick={() => setMode(signup ? "login" : "signup")} className="font-semibold text-brand-600 hover:text-brand-700">
            {signup ? "Sign in" : "Create an account"}
          </button>
        </p>
      </div>
      {signup && (
        <Field icon={<User className="size-4" />} label="Full name">
          <Input value={name} onChange={(e) => setName(e.target.value)} autoComplete="name" required placeholder="Priya Sharma" />
        </Field>
      )}
      <Field icon={<Mail className="size-4" />} label="Email">
        <Input type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" required placeholder="you@example.com" />
      </Field>
      <Field
        icon={<Lock className="size-4" />}
        label="Password"
        trailing={
          <button type="button" onClick={() => setShowPassword((s) => !s)} className="p-1 text-ink-400 hover:text-ink-700" aria-label={showPassword ? "Hide password" : "Show password"}>
            {showPassword ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
          </button>
        }
      >
        <Input
          type={showPassword ? "text" : "password"}
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          autoComplete={signup ? "new-password" : "current-password"}
          required
          minLength={signup ? 8 : undefined}
          placeholder={signup ? "At least 8 characters" : "••••••••"}
        />
      </Field>
      {error && <p className="animate-fade-up rounded-xl bg-rose-50 px-3 py-2 text-sm font-medium text-rose-700">{error}</p>}
      <Button type="submit" size="lg" className="w-full" loading={loading}>
        {signup ? "Create account" : "Sign in"}
      </Button>
    </form>
  );
}

function PhoneForm({ onSignedIn }: { onSignedIn: (u: Awaited<ReturnType<typeof api.auth.verifyOtp>>, welcome: string) => void }) {
  const [phone, setPhone] = useState("");
  const [sent, setSent] = useState(false);
  const [digits, setDigits] = useState<string[]>(Array(6).fill(""));
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const refs = useRef<(HTMLInputElement | null)[]>([]);
  const e164 = `+91${phone}`;

  async function send(e?: FormEvent) {
    e?.preventDefault();
    setError(null);
    setLoading(true);
    try {
      await api.auth.sendOtp(e164);
      setSent(true);
      setTimeout(() => refs.current[0]?.focus(), 50);
    } catch (err) {
      setError(message(err));
    } finally {
      setLoading(false);
    }
  }

  async function verify(code: string) {
    setError(null);
    setLoading(true);
    try {
      onSignedIn(await api.auth.verifyOtp(e164, code), "You're signed in!");
    } catch (err) {
      setError(message(err));
      setDigits(Array(6).fill(""));
      refs.current[0]?.focus();
    } finally {
      setLoading(false);
    }
  }

  function setDigit(i: number, raw: string) {
    const chars = raw.replace(/\D/g, "");
    if (!chars) {
      setDigits((d) => d.map((v, j) => (j === i ? "" : v)));
      return;
    }
    // Supports paste of the full code into any box.
    const next = [...digits];
    for (let k = 0; k < chars.length && i + k < 6; k++) next[i + k] = chars[k]!;
    setDigits(next);
    refs.current[Math.min(i + chars.length, 5)]?.focus();
    if (next.every(Boolean)) void verify(next.join(""));
  }

  if (!sent) {
    return (
      <form onSubmit={send} className="space-y-4">
        <div>
          <h1 className="font-display text-2xl font-bold">Sign in with your mobile</h1>
          <p className="mt-1 text-sm text-ink-500">We'll text you a 6-digit code. New here? We'll create your account.</p>
        </div>
        <label className="block">
          <span className="text-sm font-semibold text-ink-700">Mobile number</span>
          <div className="mt-1.5 flex h-12 items-center rounded-xl border border-ink-200 focus-within:border-brand-400 focus-within:ring-4 focus-within:ring-brand-500/10">
            <span className="border-r border-ink-200 px-3 text-sm font-semibold text-ink-600">🇮🇳 +91</span>
            <input
              type="tel"
              inputMode="numeric"
              value={phone}
              onChange={(e) => setPhone(e.target.value.replace(/\D/g, "").slice(0, 10))}
              autoComplete="tel-national"
              placeholder="98765 43210"
              required
              className="w-full bg-transparent px-3 text-base tracking-wide focus:outline-none"
            />
          </div>
        </label>
        {error && <p className="animate-fade-up rounded-xl bg-rose-50 px-3 py-2 text-sm font-medium text-rose-700">{error}</p>}
        <Button type="submit" size="lg" className="w-full" loading={loading} disabled={phone.length !== 10}>
          Send code
        </Button>
      </form>
    );
  }

  return (
    <div className="space-y-5">
      <div>
        <h1 className="font-display text-2xl font-bold">Enter the code</h1>
        <p className="mt-1 text-sm text-ink-500">
          Sent to +91 {phone.slice(0, 5)} {phone.slice(5)} ·{" "}
          <button onClick={() => setSent(false)} className="font-semibold text-brand-600">
            Change
          </button>
        </p>
      </div>
      <div className="flex justify-between gap-2">
        {digits.map((d, i) => (
          <input
            key={i}
            ref={(el) => {
              refs.current[i] = el;
            }}
            value={d}
            onChange={(e) => setDigit(i, e.target.value)}
            onKeyDown={(e) => e.key === "Backspace" && !d && i > 0 && refs.current[i - 1]?.focus()}
            inputMode="numeric"
            autoComplete={i === 0 ? "one-time-code" : "off"}
            aria-label={`Digit ${i + 1}`}
            className="size-12 rounded-xl border border-ink-200 text-center font-display text-xl font-bold focus:border-brand-400 focus:ring-4 focus:ring-brand-500/10 focus:outline-none sm:size-14"
          />
        ))}
      </div>
      {USE_MOCKS && (
        <p className="rounded-xl bg-ink-100 px-3 py-2 text-xs text-ink-600">
          Demo mode: use code <span className="font-mono font-bold">{MOCK_OTP}</span>
        </p>
      )}
      {error && <p className="animate-fade-up rounded-xl bg-rose-50 px-3 py-2 text-sm font-medium text-rose-700">{error}</p>}
      <Button size="lg" className="w-full" loading={loading} disabled={!digits.every(Boolean)} onClick={() => verify(digits.join(""))}>
        Verify & continue
      </Button>
      <button onClick={() => send()} className="w-full text-center text-sm font-semibold text-ink-500 hover:text-brand-600">
        Resend code
      </button>
    </div>
  );
}

function Field({ icon, label, trailing, children }: { icon: ReactNode; label: string; trailing?: ReactNode; children: ReactNode }) {
  return (
    <label className="block">
      <span className="text-sm font-semibold text-ink-700">{label}</span>
      <div className="mt-1.5 flex h-12 items-center gap-2 rounded-xl border border-ink-200 px-3 text-ink-400 focus-within:border-brand-400 focus-within:ring-4 focus-within:ring-brand-500/10">
        {icon}
        {children}
        {trailing}
      </div>
    </label>
  );
}

function Input(props: InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} className="h-full w-full min-w-0 bg-transparent text-sm text-ink-900 placeholder:text-ink-400 focus:outline-none" />;
}

function GoogleIcon() {
  return (
    <svg viewBox="0 0 24 24" className="size-5" aria-hidden>
      <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" />
      <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" />
      <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l3.66-2.84z" />
      <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" />
    </svg>
  );
}
