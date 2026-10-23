import { AlertTriangle, CheckCircle2, OctagonAlert } from "lucide-react";
import type { ButtonHTMLAttributes, ReactNode } from "react";

import type { Confidence, Status } from "../mock/types";

export const cx = (...classes: (string | false | null | undefined)[]) => classes.filter(Boolean).join(" ");

export function Card({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cx("rounded-xl border border-slate-200 bg-white", className)}>{children}</div>;
}

export function SectionTitle({ children, aside }: { children: ReactNode; aside?: ReactNode }) {
  return (
    <div className="mb-3 flex items-baseline justify-between gap-3">
      <h2 className="text-base font-semibold text-slate-900">{children}</h2>
      {aside && <div className="text-sm text-slate-500">{aside}</div>}
    </div>
  );
}

export function PageHeader({ title, meta, actions }: { title: string; meta?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">{title}</h1>
        {meta && <div className="mt-1 text-sm text-slate-500">{meta}</div>}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </div>
  );
}

type Variant = "primary" | "secondary" | "ghost";

const VARIANTS: Record<Variant, string> = {
  primary: "bg-slate-900 text-white hover:bg-slate-700",
  secondary: "border border-slate-300 bg-white text-slate-800 hover:bg-slate-50",
  ghost: "text-slate-700 hover:bg-slate-100",
};

/** Button look for links (a link must not wrap a <button>). */
export const buttonClass = (variant: Variant = "secondary", className?: string) =>
  cx(
    "inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium transition-colors disabled:opacity-50",
    VARIANTS[variant],
    className,
  );

export function Button({
  variant = "secondary",
  className,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant }) {
  return <button type="button" className={buttonClass(variant, className)} {...props} />;
}

// Status colors come from the reserved status palette and always travel with an icon and a label.
const STATUS = {
  good: { color: "#0ca30c", Icon: CheckCircle2, label: "Норма" },
  warning: { color: "#c98500", Icon: AlertTriangle, label: "Внимание" },
  critical: { color: "#d03b3b", Icon: OctagonAlert, label: "Проблема" },
} as const;

export function StatusIcon({ status, size = 16 }: { status: Status; size?: number }) {
  const { color, Icon, label } = STATUS[status];
  return <Icon size={size} color={color} aria-label={label} className="shrink-0" />;
}

export function StatusChip({ status, label }: { status: Status; label?: string }) {
  return (
    <span className="inline-flex items-center gap-1 text-xs font-medium text-slate-700">
      <StatusIcon status={status} size={14} />
      {label ?? STATUS[status].label}
    </span>
  );
}

export function Pill({ children, tone = "neutral" }: { children: ReactNode; tone?: "neutral" | "loss" | "gain" | "info" }) {
  const tones = {
    neutral: "bg-slate-100 text-slate-700",
    loss: "bg-red-50 text-red-800",
    gain: "bg-emerald-50 text-emerald-800",
    info: "bg-blue-50 text-blue-800",
  };
  return <span className={cx("inline-flex rounded-full px-2 py-0.5 text-xs font-medium", tones[tone])}>{children}</span>;
}

const CONFIDENCE: Record<Confidence, string> = { high: "Высокая", medium: "Средняя", low: "Низкая" };

export function ConfidenceBadge({ confidence, note }: { confidence: Confidence; note?: string }) {
  const bars = { high: 3, medium: 2, low: 1 }[confidence];
  return (
    <span className="inline-flex items-center gap-1.5 text-xs text-slate-600" title={note}>
      <span className="inline-flex items-end gap-0.5" aria-hidden>
        {[1, 2, 3].map((i) => (
          <span key={i} className={cx("w-1 rounded-sm", i <= bars ? "bg-slate-700" : "bg-slate-300")} style={{ height: 4 + i * 3 }} />
        ))}
      </span>
      Уверенность: {CONFIDENCE[confidence].toLowerCase()}
    </span>
  );
}

export function StatTile({
  label,
  value,
  sub,
  tone,
}: {
  label: string;
  value: string;
  sub?: ReactNode;
  tone?: "loss" | "gain";
}) {
  return (
    <Card className="p-4">
      <div className="text-sm text-slate-500">{label}</div>
      <div
        className={cx(
          "mt-1 text-xl font-semibold tabular-nums sm:text-2xl",
          tone === "loss" ? "text-red-700" : tone === "gain" ? "text-emerald-700" : "text-slate-900",
        )}
      >
        {value}
      </div>
      {sub && <div className="mt-1 text-xs text-slate-500">{sub}</div>}
    </Card>
  );
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="rounded-xl border border-dashed border-slate-300 bg-white p-6 text-center">
      <div className="font-medium text-slate-800">{title}</div>
      {children && <div className="mt-1 text-sm text-slate-500">{children}</div>}
    </div>
  );
}
