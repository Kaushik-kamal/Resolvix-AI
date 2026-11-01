import clsx from "clsx";
import type { ButtonHTMLAttributes, ReactNode } from "react";

export interface PageHeaderProps {
  title: string;
  subtitle?: ReactNode;
  /** right-aligned controls (filters, buttons) */
  actions?: ReactNode;
}

/** Title row used at the top of every page. */
export function PageHeader({ title, subtitle, actions }: PageHeaderProps) {
  return (
    <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-xl font-semibold text-ink">{title}</h1>
        {subtitle ? <p className="mt-0.5 text-xs text-ink-soft">{subtitle}</p> : null}
      </div>
      {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
    </div>
  );
}

export interface PanelProps {
  title?: ReactNode;
  /** right side of the panel header */
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  /** drop the inner padding (tables) */
  flush?: boolean;
}

/** White bordered card with an optional header row. */
export function Panel({ title, actions, children, className, flush }: PanelProps) {
  return (
    <section className={clsx("card", className)}>
      {title || actions ? (
        <header className="flex items-center justify-between gap-2 border-b border-line px-4 py-2.5">
          <h2 className="text-sm font-semibold text-ink">{title}</h2>
          {actions}
        </header>
      ) : null}
      <div className={flush ? undefined : "p-4"}>{children}</div>
    </section>
  );
}

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "primary" | "secondary" | "danger" | "ghost";
  size?: "sm" | "md";
}

/** `btn` classes as a component. type defaults to "button" so it never submits a form by accident. */
export function Button({ variant = "secondary", size = "md", className, type = "button", ...rest }: ButtonProps) {
  return (
    <button
      type={type}
      className={clsx("btn", `btn-${variant}`, size === "sm" && "btn-sm", className)}
      {...rest}
    />
  );
}
