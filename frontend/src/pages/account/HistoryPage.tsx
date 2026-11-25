import { ArrowUpRight, History, Search, X } from "lucide-react";
import { Link } from "react-router";

import { Button, ButtonLink } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { Skeleton } from "@/components/ui/Skeleton";
import { useDeleteHistory, useSearchHistory } from "@/hooks/queries";
import { formatRelativeTime } from "@/lib/format";

import { AccountShell } from "./AccountShell";

export function HistoryPage() {
  const { data, isLoading } = useSearchHistory();
  const del = useDeleteHistory();

  return (
    <AccountShell
      title="Search history"
      subtitle="Your recent searches. Only you can see this."
      action={
        data?.length ? (
          <Button variant="secondary" size="sm" onClick={() => del.mutate("all")} loading={del.isPending && del.variables === "all"}>
            Clear all
          </Button>
        ) : null
      }
    >
      {isLoading || !data ? (
        <Skeleton className="h-64 rounded-3xl" />
      ) : data.length === 0 ? (
        <EmptyState
          icon={History}
          title="No searches yet"
          body="Searches you make while signed in will show up here."
          action={<ButtonLink to="/">Start searching</ButtonLink>}
        />
      ) : (
        <ul className="divide-y divide-ink-100 overflow-hidden rounded-3xl border border-ink-100 bg-white shadow-card">
          {data.map((h) => (
            <li key={h.id} className="group flex items-center gap-4 px-5 py-3.5 hover:bg-surface">
              <Search className="size-4 shrink-0 text-ink-400" />
              <Link to={`/search?q=${encodeURIComponent(h.query)}`} className="flex-1 truncate font-medium text-ink-800 group-hover:text-brand-600">
                {h.query}
              </Link>
              <span className="hidden text-xs text-ink-400 sm:block">{formatRelativeTime(h.created_at)}</span>
              <Link to={`/search?q=${encodeURIComponent(h.query)}`} className="rounded-lg p-1.5 text-ink-400 hover:bg-ink-100 hover:text-ink-700" aria-label={`Search ${h.query} again`}>
                <ArrowUpRight className="size-4" />
              </Link>
              <button onClick={() => del.mutate(h.id)} className="rounded-lg p-1.5 text-ink-400 hover:bg-rose-50 hover:text-rose-600" aria-label={`Remove ${h.query}`}>
                <X className="size-4" />
              </button>
            </li>
          ))}
        </ul>
      )}
    </AccountShell>
  );
}
