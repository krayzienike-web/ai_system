import { AlertTriangle, CheckCircle2, Info, OctagonAlert } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { type ButtonHTMLAttributes, type ReactNode, useEffect, useId, useState } from "react";

export const cx = (...classes: (string | false | null | undefined)[]) => classes.filter(Boolean).join(" ");

export const EASE = [0.2, 0.8, 0.2, 1] as const;

// ------------------------------------------------------------------ buttons

type Variant = "primary" | "secondary" | "ghost" | "danger";
type Size = "sm" | "md" | "lg";

const VARIANTS: Record<Variant, string> = {
  primary: "bg-brand text-white shadow-sm hover:bg-brand-strong",
  secondary: "border border-line-strong bg-surface text-ink hover:border-ink-3 hover:bg-paper",
  ghost: "text-ink-2 hover:bg-ink/5 hover:text-ink",
  danger: "border border-loss/30 bg-surface text-loss hover:bg-loss-soft",
};
const SIZES: Record<Size, string> = {
  sm: "h-8 px-3 text-[13px]",
  md: "h-10 px-4 text-sm",
  lg: "h-12 px-5 text-[15px]",
};

/** Button look for links too (a link must not wrap a <button>). */
export const buttonClass = (variant: Variant = "secondary", size: Size = "md", className?: string) =>
  cx(
    "inline-flex shrink-0 items-center justify-center gap-2 rounded-[10px] font-medium transition-colors duration-150 disabled:pointer-events-none disabled:opacity-50",
    VARIANTS[variant],
    SIZES[size],
    className,
  );

export function Button({
  variant = "secondary",
  size = "md",
  className,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: Size }) {
  return <button type="button" className={buttonClass(variant, size, className)} {...props} />;
}

// ------------------------------------------------------------------ surfaces

export function Card({ children, className, raised }: { children: ReactNode; className?: string; raised?: boolean }) {
  return (
    <div className={cx("rounded-[16px] border border-line bg-surface", raised && "shadow-[var(--shadow-raised)]", className)}>
      {children}
    </div>
  );
}

/** Staggered entrance for page sections: shows reading order, skipped with reduced motion. */
export function Reveal({ children, index = 0, className }: { children: ReactNode; index?: number; className?: string }) {
  return (
    <motion.div
      className={className}
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, ease: EASE, delay: index * 0.05 }}
    >
      {children}
    </motion.div>
  );
}

/**
 * The block anatomy (docs/ux/02 §7): question → one-line answer → visual → one action → source.
 */
export function QuestionBlock({
  question,
  answer,
  children,
  action,
  source,
  className,
}: {
  question: string;
  answer?: ReactNode;
  children?: ReactNode;
  action?: ReactNode;
  source?: ReactNode;
  className?: string;
}) {
  return (
    <section className={cx("rounded-[16px] border border-line bg-surface p-5 sm:p-6", className)}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 max-w-[70ch]">
          <h2 className="text-[13px] font-semibold uppercase tracking-[0.06em] text-ink-3">{question}</h2>
          {answer && <div className="mt-1.5 text-[17px] font-medium leading-snug text-ink">{answer}</div>}
        </div>
        {action && <div className="flex shrink-0 flex-wrap gap-2">{action}</div>}
      </div>
      {children && <div className="mt-5">{children}</div>}
      {source && <div className="mt-4 border-t border-line pt-3 text-xs text-ink-3">{source}</div>}
    </section>
  );
}

export function PageTitle({ title, subtitle, actions }: { title: ReactNode; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        <h1 className="font-display text-[26px] font-semibold leading-tight tracking-tight sm:text-[30px]">{title}</h1>
        {subtitle && <div className="mt-1.5 text-sm text-ink-3">{subtitle}</div>}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </div>
  );
}

// ------------------------------------------------------------------ status

export type Tone = "loss" | "gain" | "warn" | "info" | "neutral" | "brand";

const TONES: Record<Tone, string> = {
  loss: "bg-loss-soft text-loss",
  gain: "bg-gain-soft text-gain",
  warn: "bg-warn-soft text-warn",
  info: "bg-info-soft text-info",
  neutral: "bg-ink/5 text-ink-2",
  brand: "bg-brand-soft text-brand-strong",
};

const TONE_ICON: Partial<Record<Tone, typeof Info>> = {
  loss: OctagonAlert,
  gain: CheckCircle2,
  warn: AlertTriangle,
  info: Info,
};

/** A status always carries an icon and a word, never color alone. */
export function Pill({ tone = "neutral", children, icon = true }: { tone?: Tone; children: ReactNode; icon?: boolean }) {
  const Icon = icon ? TONE_ICON[tone] : undefined;
  return (
    <span className={cx("inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium", TONES[tone])}>
      {Icon && <Icon size={12} aria-hidden />}
      {children}
    </span>
  );
}

// ------------------------------------------------------------------ glossary term

/** A term with a plain-language explanation on hover/focus (dotted underline). */
export function Term({ children, hint }: { children: ReactNode; hint: string }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  return (
    <span className="relative inline-block">
      <button
        type="button"
        className="cursor-help border-b border-dotted border-current"
        aria-describedby={id}
        onMouseEnter={() => setOpen(true)}
        onMouseLeave={() => setOpen(false)}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
      >
        {children}
      </button>
      <AnimatePresence>
        {open && (
          <motion.span
            id={id}
            role="tooltip"
            initial={{ opacity: 0, y: 4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.15 }}
            className="absolute bottom-full left-1/2 z-50 mb-2 w-64 -translate-x-1/2 rounded-lg bg-ink px-3 py-2 text-left text-xs font-normal normal-case leading-relaxed tracking-normal text-white shadow-[var(--shadow-float)]"
          >
            {hint}
          </motion.span>
        )}
      </AnimatePresence>
    </span>
  );
}

// ------------------------------------------------------------------ dialog & toast

export function Dialog({
  open,
  onClose,
  title,
  children,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
}) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);
  return (
    <AnimatePresence>
      {open && (
        <motion.div
          className="fixed inset-0 z-50 flex items-end justify-center bg-ink/30 p-4 sm:items-center"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          onClick={onClose}
        >
          <motion.div
            role="dialog"
            aria-modal="true"
            aria-label={title}
            className="w-full max-w-lg rounded-[24px] bg-surface p-6 shadow-[var(--shadow-float)]"
            initial={{ y: 24, scale: 0.98 }}
            animate={{ y: 0, scale: 1 }}
            exit={{ y: 12, opacity: 0 }}
            transition={{ duration: 0.25, ease: EASE }}
            onClick={(e) => e.stopPropagation()}
          >
            <h2 className="font-display text-lg font-semibold">{title}</h2>
            <div className="mt-4">{children}</div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cx("animate-pulse rounded-lg bg-ink/5", className)} />;
}

/** The server's reason a request failed (it is written for people), or `fallback` when there is none. */
export function ErrorText({ error, fallback = "Не получилось, попробуйте еще раз", className }: { error: unknown; fallback?: string; className?: string }) {
  if (!error) return null;
  const text = error instanceof Error && error.message && !/^\d{3}\b/.test(error.message) ? error.message : fallback;
  return (
    <p role="alert" className={cx("text-sm text-loss", className)}>
      {text}
    </p>
  );
}

/** A screen whose data did not load: says so (with the server's reason) instead of loading forever. */
export function LoadError({ error, title = "Не получилось загрузить данные" }: { error: unknown; title?: string }) {
  return (
    <EmptyState title={title}>
      <ErrorText error={error} fallback="Обновите страницу чуть позже." className="text-ink-3" />
    </EmptyState>
  );
}

export function EmptyState({ title, children, action }: { title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="rounded-[16px] border border-dashed border-line-strong bg-surface px-6 py-10 text-center">
      <div className="font-medium text-ink">{title}</div>
      {children && <div className="mx-auto mt-1 max-w-md text-sm text-ink-3">{children}</div>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}
