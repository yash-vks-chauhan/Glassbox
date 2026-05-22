import Link from "next/link";
import { ArrowLeft, SearchX } from "lucide-react";

import { ButtonLink } from "@/components/ButtonLink";
import { NewClientDialog } from "@/components/clients/NewClientDialog";
import { Button } from "@/components/ui/button";

export function ClientMissingState({ id }: { id: string }) {
  return (
    <div className="mx-auto max-w-[760px] px-5 py-12 lg:px-8 lg:py-16">
      <div className="rounded-xl border border-dashed bg-card/50 p-8 text-center">
        <div
          className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-lg"
          style={{
            background: "hsl(var(--state-refused-soft))",
            color: "hsl(var(--state-refused-soft-foreground))",
          }}
        >
          <SearchX className="h-5 w-5" />
        </div>
        <h1 className="font-serif text-2xl font-semibold tracking-tight">
          No client with ID <span className="font-mono">{id}</span>
        </h1>
        <p className="mx-auto mt-2 max-w-md text-sm leading-6 text-muted-foreground">
          The roster doesn't include this client. It may have been removed, never added,
          or the URL was mistyped.
        </p>
        <div className="mt-6 flex flex-wrap items-center justify-center gap-2">
          <ButtonLink href="/app/clients" variant="outline" className="h-9 rounded-md">
            <ArrowLeft className="h-3.5 w-3.5" />
            Back to clients
          </ButtonLink>
          <NewClientDialog
            trigger={
              <Button className="h-9 rounded-md">Add a new client</Button>
            }
          />
        </div>
      </div>
    </div>
  );
}
