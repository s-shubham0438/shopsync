import { LoaderCircle } from "lucide-react";

import { cn } from "@/lib/cn";

export function Spinner({ className }: { className?: string }) {
  return <LoaderCircle className={cn("size-5 animate-spin", className)} aria-hidden />;
}

export function PageSpinner() {
  return (
    <div className="grid min-h-[50vh] place-items-center" role="status" aria-label="Loading">
      <Spinner className="size-8 text-brand-500" />
    </div>
  );
}
