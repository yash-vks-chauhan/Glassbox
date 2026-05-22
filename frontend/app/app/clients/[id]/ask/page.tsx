"use client";

import { use } from "react";

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
  const { client, isHydrated } = useClient(id);

  if (!client) {
    if (!isHydrated) {
      return (
        <div className="mx-auto max-w-[1480px] px-5 py-6 lg:px-8 lg:py-8">
          <Skeleton className="h-[80vh] w-full rounded-xl" />
        </div>
      );
    }
    return <ClientMissingState id={id} />;
  }

  return (
    <>
      <ClientContextBar client={client} activeTab="ask" />
      <Conversation client={client} />
    </>
  );
}
