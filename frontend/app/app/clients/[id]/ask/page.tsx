"use client";

import { Suspense, use, useCallback } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

import { ClientContextBar } from "@/components/clients/ClientContextBar";
import { ClientMissingState } from "@/components/clients/ClientMissingState";
import { Conversation } from "@/components/conversation/Conversation";
import { Skeleton } from "@/components/ui/skeleton";
import { useClient } from "@/lib/clients-hooks";

export default function ClientAskPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  return (
    <Suspense fallback={<AskSkeleton />}>
      <ClientAsk id={id} />
    </Suspense>
  );
}

function ClientAsk({ id }: { id: string }) {
  const { client, isHydrated } = useClient(id);
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const threadId = searchParams.get("thread");

  // The open thread lives in the URL so a reload or a shared link reopens it.
  const onThreadChange = useCallback(
    (next: string | null) => {
      router.replace(next ? `${pathname}?thread=${encodeURIComponent(next)}` : pathname, {
        scroll: false,
      });
    },
    [pathname, router],
  );

  if (!client) {
    if (!isHydrated) return <AskSkeleton />;
    return <ClientMissingState id={id} />;
  }

  return (
    <>
      <ClientContextBar client={client} activeTab="ask" />
      <Conversation client={client} threadId={threadId} onThreadChange={onThreadChange} />
    </>
  );
}

function AskSkeleton() {
  return (
    <div className="mx-auto max-w-[1480px] px-5 py-6 lg:px-8 lg:py-8">
      <Skeleton className="h-[80vh] w-full rounded-xl" />
    </div>
  );
}
