import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

export function EmptyState({
  icon: Icon,
  title,
  body,
  action,
}: {
  icon: LucideIcon;
  title: string;
  body?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center rounded-3xl border border-dashed border-ink-200 bg-white px-6 py-16 text-center">
      <div className="mb-5 grid size-16 place-items-center rounded-2xl bg-brand-50 text-brand-500 ring-8 ring-brand-50/50">
        <Icon className="size-7" />
      </div>
      <h3 className="font-display text-xl font-semibold text-ink-900">{title}</h3>
      {body && <p className="mt-2 max-w-md text-sm text-ink-500">{body}</p>}
      {action && <div className="mt-6">{action}</div>}
    </div>
  );
}
