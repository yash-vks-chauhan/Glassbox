"use client";

import { useEffect, useState } from "react";

import {
  CHANGE_EVENT,
  ClientRecord,
  SEED_CLIENTS,
  loadAllClients,
} from "@/lib/clients";

export function useClients(): {
  clients: ClientRecord[];
  isHydrated: boolean;
  reload: () => void;
} {
  // SSR + first client render returns seed only so server and client agree
  // on the initial markup. After mount we read localStorage and re-render.
  const [clients, setClients] = useState<ClientRecord[]>(SEED_CLIENTS);
  const [isHydrated, setIsHydrated] = useState(false);

  function refresh() {
    setClients(loadAllClients());
    setIsHydrated(true);
  }

  useEffect(() => {
    refresh();
    const onChange = () => refresh();
    window.addEventListener(CHANGE_EVENT, onChange);
    window.addEventListener("storage", onChange);
    return () => {
      window.removeEventListener(CHANGE_EVENT, onChange);
      window.removeEventListener("storage", onChange);
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
