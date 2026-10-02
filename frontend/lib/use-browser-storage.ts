"use client";

import { useSyncExternalStore } from "react";

type Area = "local" | "session";

const CHANGE_EVENT = "glassbox-storage-change";

function storageFor(area: Area): Storage | null {
  try {
    return area === "local" ? window.localStorage : window.sessionStorage;
  } catch {
    return null; // blocked storage (some private windows)
  }
}

function subscribe(listener: () => void) {
  window.addEventListener("storage", listener);
  window.addEventListener(CHANGE_EVENT, listener);
  return () => {
    window.removeEventListener("storage", listener);
    window.removeEventListener(CHANGE_EVENT, listener);
  };
}

/** Read a browser-storage key as a string (null when missing, blocked, or
 * during server rendering). Re-renders when writeBrowserStorage changes it. */
export function useBrowserStorage(area: Area, key: string): string | null {
  return useSyncExternalStore(
    subscribe,
    () => storageFor(area)?.getItem(key) ?? null,
    () => null,
  );
}

/** Write (or with null, remove) a key and notify useBrowserStorage readers. */
export function writeBrowserStorage(area: Area, key: string, value: string | null) {
  const storage = storageFor(area);
  if (!storage) return;
  try {
    if (value === null) storage.removeItem(key);
    else storage.setItem(key, value);
  } catch {
    return;
  }
  window.dispatchEvent(new Event(CHANGE_EVENT));
}
