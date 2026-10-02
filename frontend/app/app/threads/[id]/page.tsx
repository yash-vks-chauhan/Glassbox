"use client";

import { use, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { PageContainer } from "@/components/PageContainer";
import { getThread } from "@/lib/api";
import { threadHref } from "@/lib/threads";

/** A thread opens inside its client's conversation view. */
export default function ThreadRedirect({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const router = useRouter();
  const [missing, setMissing] = useState(false);

  useEffect(() => {
    getThread(id)
      .then((thread) => router.replace(threadHref(thread)))
      .catch(() => setMissing(true));
  }, [id, router]);

  return (
    <PageContainer>
      <p className="text-sm text-muted-foreground">
        {missing ? (
          <>
            This thread doesn&apos;t exist or isn&apos;t visible to you.{" "}
            <Link href="/app/threads" className="text-primary">
              Back to threads
            </Link>
          </>
        ) : (
          "Opening thread…"
        )}
      </p>
    </PageContainer>
  );
}
