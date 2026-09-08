import type { ButtonHTMLAttributes, ReactNode } from "react";

export function cx(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(" ");
}

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "ghost" | "danger";
  size?: "sm" | "md" | "lg";
};

export function Button({
  variant = "secondary",
  size = "md",
  className,
  ...props
}: ButtonProps) {
  const variants = {
    primary:
      "bg-accent text-[#06210f] font-semibold hover:brightness-110 disabled:hover:brightness-100",
    secondary:
      "bg-raised text-text border border-border hover:border-border-strong hover:bg-[#212938]",
    ghost: "text-dim hover:text-text hover:bg-raised",
    danger: "bg-raised text-wrong border border-border hover:border-wrong",
  };
  const sizes = {
    sm: "h-8 px-3 text-sm",
    md: "h-10 px-4 text-sm",
    lg: "h-12 px-6 text-base",
  };
  return (
    <button
      className={cx(
        "inline-flex items-center justify-center gap-2 rounded-lg transition-[background-color,border-color,filter,transform] duration-100",
        "active:scale-[0.985] disabled:cursor-not-allowed disabled:opacity-45 disabled:active:scale-100",
        variants[variant],
        sizes[size],
        className,
      )}
      {...props}
    />
  );
}

export function Card({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cx(
        "rounded-card border border-border bg-surface p-5",
        className,
      )}
    >
      {children}
    </div>
  );
}

export function Kbd({ children }: { children: ReactNode }) {
  return <span className="kbd">{children}</span>;
}

export function Stat({
  label,
  value,
  hint,
}: {
  label: string;
  value: ReactNode;
  hint?: string;
}) {
  return (
    <div className="rounded-card border border-border bg-surface px-4 py-3">
      <div className="text-[11px] font-medium uppercase tracking-wider text-faint">
        {label}
      </div>
      <div className="tabular mt-1 text-2xl font-semibold text-text">{value}</div>
      {hint && <div className="mt-0.5 text-xs text-faint">{hint}</div>}
    </div>
  );
}

export function Bar({ value, tone = "accent" }: { value: number; tone?: string }) {
  return (
    <div
      className="h-1.5 w-full overflow-hidden rounded-full bg-raised"
      role="progressbar"
      aria-valuenow={Math.round(value * 100)}
      aria-valuemin={0}
      aria-valuemax={100}
    >
      <div
        className="h-full rounded-full transition-[width] duration-300 ease-out"
        style={{
          width: `${Math.min(100, Math.max(0, value * 100))}%`,
          backgroundColor: `var(--color-${tone})`,
        }}
      />
    </div>
  );
}

export function Pill({
  children,
  tone = "faint",
}: {
  children: ReactNode;
  tone?: "faint" | "accent" | "wrong" | "partial" | "info";
}) {
  const tones = {
    faint: "border-border text-faint",
    accent: "border-accent/40 text-accent",
    wrong: "border-wrong/40 text-wrong",
    partial: "border-partial/40 text-partial",
    info: "border-info/40 text-info",
  };
  return (
    <span
      className={cx(
        "inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-medium",
        tones[tone],
      )}
    >
      {children}
    </span>
  );
}

export function Empty({
  title,
  children,
}: {
  title: string;
  children?: ReactNode;
}) {
  return (
    <div className="rounded-card border border-dashed border-border px-6 py-12 text-center">
      <p className="text-text">{title}</p>
      {children && <div className="mt-2 text-sm text-dim">{children}</div>}
    </div>
  );
}

export function Spinner({ label }: { label?: string }) {
  return (
    <span className="inline-flex items-center gap-2 text-sm text-dim">
      <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-border border-t-accent" />
      {label}
    </span>
  );
}
