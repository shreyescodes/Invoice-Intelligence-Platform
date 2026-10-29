import { FileSearch, ScanText, ShieldCheck, Workflow } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";

import { Logo } from "@/components/Logo";
import { Button } from "@/components/ui/Button";
import { Callout } from "@/components/ui/Feedback";
import { Input, Label } from "@/components/ui/Field";
import { useAuth } from "@/lib/auth-context";
import { useMeta } from "@/lib/queries";

const FEATURES = [
  { icon: ScanText, title: "Capture", text: "Header fields and line items read from PDFs, with per-field confidence." },
  { icon: FileSearch, title: "3-way match", text: "Every invoice checked against the ERP purchase order and goods receipt." },
  { icon: ShieldCheck, title: "Risk scoring", text: "Duplicates, price drift and unusual amounts routed to a human." },
  { icon: Workflow, title: "Straight-through", text: "Clean invoices approved and posted to the ERP automatically." },
];

export function LoginPage() {
  const { user, signIn } = useAuth();
  const { data: meta } = useMeta();
  const navigate = useNavigate();
  const location = useLocation();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const from = (location.state as { from?: string } | null)?.from ?? "/";

  if (user) return <Navigate to={from} replace />;

  async function submit(event: FormEvent) {
    event.preventDefault();
    setPending(true);
    setError(null);
    try {
      await signIn(email, password);
      navigate(from, { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sign-in failed");
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="grid min-h-full lg:grid-cols-[1.05fr_1fr]">
      <section className="relative hidden overflow-hidden border-r border-line bg-surface-2 lg:flex lg:flex-col lg:justify-between lg:p-12">
        <Logo />
        <div className="max-w-md">
          <h1 className="text-[28px] leading-9 font-semibold tracking-[-0.015em] text-ink">
            Accounts payable that checks every invoice, and only asks you about the ones that matter.
          </h1>
          <ul className="mt-8 space-y-5">
            {FEATURES.map(({ icon: Icon, title, text }) => (
              <li key={title} className="flex gap-3">
                <div className="grid size-8 shrink-0 place-items-center rounded-lg bg-surface ring-1 ring-line">
                  <Icon className="size-4 text-accent" aria-hidden />
                </div>
                <div>
                  <div className="text-sm font-semibold text-ink">{title}</div>
                  <div className="text-[13px] text-ink-2">{text}</div>
                </div>
              </li>
            ))}
          </ul>
        </div>
        <p className="text-[12px] text-ink-3">Invoice Intelligence Platform{meta ? ` · v${meta.version}` : ""}</p>
      </section>

      <section className="flex items-center justify-center px-4 py-12">
        <div className="w-full max-w-sm">
          <div className="mb-8 lg:hidden">
            <Logo />
          </div>
          <h2 className="text-xl font-semibold text-ink">Sign in</h2>
          <p className="mt-1 text-sm text-ink-2">Use your work account to continue.</p>

          <form onSubmit={submit} className="mt-6 space-y-4">
            {error && <Callout tone="critical" title={error} />}
            <div>
              <Label htmlFor="email">Email</Label>
              <Input
                id="email"
                type="email"
                autoComplete="username"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
            </div>
            <div>
              <Label htmlFor="password">Password</Label>
              <Input
                id="password"
                type="password"
                autoComplete="current-password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </div>
            <Button type="submit" variant="primary" className="w-full" loading={pending}>
              Sign in
            </Button>
          </form>

          {meta?.demo_mode && meta.demo_accounts.length > 0 && (
            <div className="mt-8 rounded-xl border border-line bg-surface p-4">
              <div className="text-[13px] font-semibold text-ink">Demo accounts</div>
              <p className="mt-0.5 text-[12px] text-ink-3">Pick a role to fill the form.</p>
              <div className="mt-3 space-y-1.5">
                {meta.demo_accounts.map((account) => (
                  <button
                    key={account.email}
                    type="button"
                    onClick={() => {
                      setEmail(account.email ?? "");
                      setPassword(account.password ?? "");
                    }}
                    className="flex w-full items-center justify-between rounded-lg px-2.5 py-2 text-left text-[13px] hover:bg-surface-hover"
                  >
                    <span>
                      <span className="font-medium text-ink">{account.name}</span>
                      <span className="ml-2 text-ink-3">{account.email}</span>
                    </span>
                    <span className="rounded-md bg-neutral-soft px-1.5 py-0.5 text-[11px] font-medium text-ink-2 capitalize">
                      {account.role}
                    </span>
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>
      </section>
    </div>
  );
}
