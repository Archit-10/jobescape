"use client";

import { ArrowLeft, BriefcaseBusiness, Compass } from "lucide-react";

import { Button } from "@/components/ui/button";

export default function NotFound() {
  return (
    <main className="relative grid min-h-dvh place-items-center overflow-hidden px-6">
      <div className="pointer-events-none absolute inset-0 opacity-70">
        <div className="fallback-pulse absolute left-[12%] top-[18%] size-40 rounded-full bg-primary/5 blur-3xl" />
        <div className="fallback-pulse absolute bottom-[12%] right-[10%] size-56 rounded-full bg-primary/5 blur-3xl" />
      </div>

      <div className="fallback-enter relative w-full max-w-md text-center">
        <div className="mx-auto mb-7 grid size-16 place-items-center rounded-2xl border border-border bg-card shadow-sm">
          <div className="fallback-orbit relative grid size-11 place-items-center rounded-full border border-dashed border-primary/40">
            <Compass className="size-5 text-primary" />
          </div>
        </div>

        <p className="mb-2 font-mono text-xs font-medium uppercase tracking-[0.18em] text-primary">Error 404</p>
        <h1 className="text-3xl font-semibold tracking-tight sm:text-4xl">This opportunity moved</h1>
        <p className="mx-auto mt-3 max-w-sm text-sm leading-6 text-muted-foreground">
          The page you opened does not exist or may have been moved. Head back to discovery and continue your search.
        </p>

        <div className="mt-7 flex items-center justify-center gap-2">
          <Button onClick={() => window.location.assign("/")}>
            <BriefcaseBusiness className="size-4" />Back to Job Scraper
          </Button>
          <Button variant="ghost" onClick={() => window.history.back()}>
            <ArrowLeft className="size-4" />Go back
          </Button>
        </div>
      </div>
    </main>
  );
}

