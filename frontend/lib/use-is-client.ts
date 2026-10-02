"use client";

import { useSyncExternalStore } from "react";

const subscribe = () => () => {};

/** False while server rendering and hydrating, true in the browser after.
 * Lets a component tell "not known yet" apart from "missing". */
export function useIsClient(): boolean {
  return useSyncExternalStore(
    subscribe,
    () => true,
    () => false,
  );
}
