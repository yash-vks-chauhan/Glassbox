"use client";

import { useEffect, useState } from "react";

import {
  CHANGE_EVENT,
  ClientRecord,
  loadAllClients,
} from "@/lib/clients";

export function useClients(): {
  clients: ClientRecord[];
  isHydrated: boolean;
  reload: () => void;
} {
  // Start empty so server-rendered HTML matches the first client render.
  // After mount we fetch from the API and re-render. Re-fetches happen when
  // anyone in the app dispatches `CHANGE_EVENT` (the New Client dialog does
  // this on a successful create).
  const [clients, setClients] = useState<ClientRecord[]>([]);
  const [isHydrated, setIsHydrated] = useState(false);

  function refresh() {
    let cancelled = false;
    loadAllClients()
      .then((rows) => {
        if (cancelled) return;
        setClients(rows);
        setIsHydrated(true);
      })
      .catch(() => {
        if (cancelled) return;
        setIsHydrated(true);
      });
    return () => {
      cancelled = true;
    };
  }

  useEffect(() => {
    const cancel = refresh();
    const onChange = () => refresh();
    window.addEventListener(CHANGE_EVENT, onChange);
    return () => {
      window.removeEventListener(CHANGE_EVENT, onChange);
      cancel();
    };
  }, []);

  return { clients, isHydrated, reload: refresh };
}

export function useClient(id: string | null | undefined): {
  client: ClientRecord | undefined;
  isHydrated: boolean;
} {
  const { clients, isHydrated } = useClients();
  const client = id ? clients.find((c) => c.id === id) : undefined;
  return { client, isHydrated };
}
