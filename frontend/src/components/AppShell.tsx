import { clsx } from "clsx";
import { Building2, FileText, Inbox, LayoutDashboard, LogOut, Menu, Moon, Sparkles, Sun, X } from "lucide-react";
import { useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";

import { Logo } from "@/components/Logo";
import { useAuth } from "@/lib/auth-context";
import { initials } from "@/lib/format";
import { useInvoices, useMeta } from "@/lib/queries";
import { useTheme } from "@/lib/theme";

const ROLE_LABEL = { admin: "Administrator", approver: "Approver", clerk: "AP clerk", viewer: "Viewer" } as const;

function ReviewCount() {
  const { data } = useInvoices({ status: ["needs_review"], pageSize: 1 });
  if (!data?.total) return null;
  return (
    <span className="tabular ml-auto rounded-full bg-warning-soft px-1.5 text-[11px] leading-[18px] font-semibold text-warning-ink">
      {data.total}
    </span>
  );
}

const NAV = [
  { to: "/", label: "Overview", icon: LayoutDashboard, end: true },
  { to: "/invoices", label: "Invoices", icon: FileText },
  { to: "/review", label: "Review queue", icon: Inbox, badge: <ReviewCount /> },
  { to: "/vendors", label: "Vendors", icon: Building2 },
  { to: "/ask", label: "Ask", icon: Sparkles },
];

function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  const { user, signOut } = useAuth();
  const { data: meta } = useMeta();
  const [theme, toggleTheme] = useTheme();

  return (
    <div className="flex h-full flex-col">
      <div className="px-4 pt-5 pb-6">
        <Logo />
      </div>
      <nav className="flex-1 space-y-0.5 px-2" aria-label="Main">
        {NAV.map(({ to, label, icon: Icon, end, badge }) => (
          <NavLink
            key={to}
            to={to}
            end={end}
            onClick={onNavigate}
            className={({ isActive }) =>
              clsx(
                "flex h-9 items-center gap-2.5 rounded-lg px-2.5 text-[13.5px] font-medium transition-colors",
                isActive ? "bg-surface text-ink shadow-card ring-1 ring-line" : "text-ink-2 hover:bg-surface-hover hover:text-ink",
              )
            }
          >
            <Icon className="size-4 shrink-0" aria-hidden />
            {label}
            {badge}
          </NavLink>
        ))}
      </nav>
      <div className="space-y-3 border-t border-line p-3">
        {meta?.demo_mode && (
          <div className="rounded-lg bg-accent-soft px-2.5 py-2 text-[12px] leading-4 text-accent-ink">
            Demo environment · v{meta.version}
          </div>
        )}
        {user && (
          <div className="flex items-center gap-2.5 px-1">
            <div className="grid size-8 shrink-0 place-items-center rounded-full bg-accent text-[12px] font-semibold text-white">
              {initials(user.full_name)}
            </div>
            <div className="min-w-0 flex-1">
              <div className="truncate text-[13px] font-medium text-ink">{user.full_name}</div>
              <div className="truncate text-[12px] text-ink-3">{ROLE_LABEL[user.role]}</div>
            </div>
            <button
              type="button"
              onClick={toggleTheme}
              className="rounded-md p-1.5 text-ink-3 hover:bg-surface-hover hover:text-ink"
              aria-label={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}
            >
              {theme === "dark" ? <Sun className="size-4" /> : <Moon className="size-4" />}
            </button>
            <button
              type="button"
              onClick={() => signOut()}
              className="rounded-md p-1.5 text-ink-3 hover:bg-surface-hover hover:text-ink"
              aria-label="Sign out"
            >
              <LogOut className="size-4" />
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

export function AppShell() {
  const [open, setOpen] = useState(false);
  const location = useLocation();

  return (
    <div className="flex h-full">
      <aside className="hidden w-60 shrink-0 border-r border-line bg-surface-2 lg:block">
        <Sidebar />
      </aside>

      {open && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <button type="button" className="absolute inset-0 bg-black/40" aria-label="Close menu" onClick={() => setOpen(false)} />
          <aside className="absolute inset-y-0 left-0 w-64 border-r border-line bg-surface-2 shadow-pop">
            <Sidebar onNavigate={() => setOpen(false)} />
          </aside>
        </div>
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 items-center gap-3 border-b border-line bg-surface px-4 lg:hidden">
          <button
            type="button"
            onClick={() => setOpen((v) => !v)}
            className="rounded-md p-1.5 text-ink-2 hover:bg-surface-hover"
            aria-label="Open menu"
          >
            {open ? <X className="size-5" /> : <Menu className="size-5" />}
          </button>
          <Logo />
        </header>
        <main className="min-h-0 flex-1 overflow-y-auto" key={location.pathname}>
          <div className="mx-auto w-full max-w-[1320px] px-4 py-6 sm:px-6 lg:px-8 lg:py-8">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  );
}
