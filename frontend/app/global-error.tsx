"use client";

import { AlertOctagon, RefreshCw } from "lucide-react";

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <html lang="en">
      <body className="min-h-dvh bg-white text-zinc-950">
        <main className="grid min-h-dvh place-items-center px-6">
          <div className="fallback-enter max-w-md text-center">
            <div className="mx-auto mb-6 grid size-14 place-items-center rounded-2xl border border-red-200 bg-red-50 text-red-600">
              <AlertOctagon className="size-6" />
            </div>
            <p className="mb-2 text-xs font-medium uppercase tracking-[0.16em] text-red-600">Application unavailable</p>
            <h1 className="text-3xl font-semibold tracking-tight">Job Scraper needs a fresh start</h1>
            <p className="mt-3 text-sm leading-6 text-zinc-500">
              The application could not render. Reload safely to restore your saved search draft.
            </p>
            {error.digest && <p className="mt-4 font-mono text-[10px] text-zinc-400">Reference {error.digest}</p>}
            <button
              type="button"
              onClick={reset}
              className="mt-7 inline-flex h-9 items-center gap-2 rounded-lg bg-indigo-600 px-4 text-sm font-medium text-white"
            >
              <RefreshCw className="size-4" />Reload application
            </button>
          </div>
        </main>
      </body>
    </html>
  );
}
