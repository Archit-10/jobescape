"use client";

import { useEffect } from "react";
import { AlertTriangle, RefreshCw } from "lucide-react";

import { Button } from "@/components/ui/button";

export default function ErrorPage({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <main className="relative grid min-h-dvh place-items-center overflow-hidden px-6">
      <div className="fallback-enter w-full max-w-md text-center">
        <div className="mx-auto mb-6 grid size-14 place-items-center rounded-2xl border border-destructive/20 bg-destructive/5">
          <AlertTriangle className="size-6 text-destructive" />
        </div>
        <p className="mb-2 text-xs font-medium uppercase tracking-[0.16em] text-destructive">Unexpected error</p>
        <h1 className="text-3xl font-semibold tracking-tight">Something interrupted the search</h1>
        <p className="mx-auto mt-3 max-w-sm text-sm leading-6 text-muted-foreground">
          Your saved draft is still available. Retry the current view or return to a fresh search.
        </p>
        {error.digest && (
          <p className="mt-4 font-mono text-[10px] text-muted-foreground">Reference {error.digest}</p>
        )}
        <div className="mt-7 flex justify-center gap-2">
          <Button onClick={reset}><RefreshCw className="size-4" />Try again</Button>
          <Button variant="outline" onClick={() => window.location.assign("/")}>New search</Button>
        </div>
      </div>
    </main>
  );
}
