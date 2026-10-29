export function LogoMark({ className = "size-7" }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={className} aria-hidden>
      <rect width="32" height="32" rx="7" fill="#1c5cab" />
      <path d="M10 7.5h8.5L23 12v12.5a1 1 0 0 1-1 1H10a1 1 0 0 1-1-1v-16a1 1 0 0 1 1-1Z" fill="#fff" />
      <path d="M18.5 7.5V12H23" fill="#cde2fb" />
      <path
        d="m12.5 18.2 2.4 2.4 4.6-4.9"
        fill="none"
        stroke="#1c5cab"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export function Logo() {
  return (
    <div className="flex items-center gap-2.5">
      <LogoMark />
      <div className="leading-tight">
        <div className="text-[14px] font-semibold tracking-[-0.01em] text-ink">Invoice Intelligence</div>
        <div className="text-[11px] text-ink-3">Accounts payable</div>
      </div>
    </div>
  );
}
