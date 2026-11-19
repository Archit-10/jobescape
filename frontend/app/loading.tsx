import { BriefcaseBusiness } from "lucide-react";
import { Skeleton } from "@/components/ui/skeleton";

export default function Loading() {
  return (
    <main className="min-h-dvh">
      <header className="h-14 border-b">
        <div className="mx-auto flex h-full max-w-[1100px] items-center px-4 sm:px-6">
          <div className="flex items-center gap-2.5">
            <div className="grid size-8 place-items-center rounded-[9px] bg-primary text-primary-foreground">
              <BriefcaseBusiness className="size-4" />
            </div>
            <span className="text-[15px] font-semibold">Job Scraper</span>
          </div>
        </div>
      </header>
      <div className="mx-auto max-w-[820px] px-4 py-12 sm:px-6 sm:py-16">
        <div className="fallback-enter">
          <Skeleton className="mb-3 h-3 w-28" />
          <Skeleton className="mb-8 h-8 w-72 max-w-full" />
          <Skeleton className="h-16 w-full rounded-xl" />
          <div className="relative mt-5 overflow-hidden">
            <div className="fallback-scan h-0.5 w-1/4 rounded-full bg-primary/70" />
          </div>
          <div className="mt-8 grid gap-4 md:grid-cols-[1fr_280px]">
            <Skeleton className="h-64 rounded-xl" />
            <Skeleton className="h-40 rounded-xl" />
          </div>
        </div>
      </div>
    </main>
  );
}
