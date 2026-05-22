// Client roster. Three are seeded from backend/corpus/ips/*.md; the rest are
// added via the New Client dialog and persisted in localStorage.
//
// We persist client-side (not in the backend) deliberately — in a real
// deployment client master data comes from the firm's CRM via SSO. GlassBox's
// job is to *know about* clients and their IPS, not to be the source of truth.
//
// This module is safe to import from both server and client components.
// React hooks (`useClients`, `useClient`) live in `lib/clients-hooks.ts`
// because Next.js forbids server components from importing modules that
// transitively depend on React hooks.

export type RiskProfile = "conservative" | "moderate" | "aggressive";

export type ClientRecord = {
  id: string;
  displayName: string;
  household: string;
  riskProfile: RiskProfile;
  jurisdictions: string[];
  maxSinglePositionPct: number;
  minLiquidWithin30dPct: number;
  excludedSectors: string[];
  excludedRegions: string[];
  ipsVersion: string;
  ipsUpdatedAt: string;
  aumEur: number;
  advisor: string;
};

export const SEED_CLIENTS: ClientRecord[] = [
  {
    id: "C001",
    displayName: "Müller Family Office",
    household: "DACH · Zurich",
    riskProfile: "moderate",
    jurisdictions: ["CH", "US"],
    maxSinglePositionPct: 25,
    minLiquidWithin30dPct: 15,
    excludedSectors: ["tobacco", "firearms"],
    excludedRegions: ["russia"],
    ipsVersion: "v3.2",
    ipsUpdatedAt: "2024-11-18",
    aumEur: 18_400_000,
    advisor: "S. Kühn",
  },
  {
    id: "C002",
    displayName: "Vance Conservative Trust",
    household: "US · Boston",
    riskProfile: "conservative",
    jurisdictions: ["US"],
    maxSinglePositionPct: 15,
    minLiquidWithin30dPct: 30,
    excludedSectors: ["tobacco", "firearms", "gambling", "cryptocurrency"],
    excludedRegions: ["russia", "sanctioned_markets"],
    ipsVersion: "v2.7",
    ipsUpdatedAt: "2025-01-09",
    aumEur: 6_900_000,
    advisor: "A. Lopez",
  },
  {
    id: "C003",
    displayName: "Tan Growth Mandate",
    household: "APAC · Singapore",
    riskProfile: "aggressive",
    jurisdictions: ["CH", "SG"],
    maxSinglePositionPct: 35,
    minLiquidWithin30dPct: 10,
    excludedSectors: ["tobacco"],
    excludedRegions: ["russia"],
    ipsVersion: "v4.0",
    ipsUpdatedAt: "2025-03-02",
    aumEur: 42_000_000,
    advisor: "M. Reis",
  },
];

export const STORAGE_KEY = "glassbox.clients.v1";
export const CHANGE_EVENT = "glassbox-clients-change";

export function readLocal(): ClientRecord[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(isClientLike);
  } catch {
    return [];
  }
}

function writeLocal(clients: ClientRecord[]) {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(clients));
  window.dispatchEvent(new Event(CHANGE_EVENT));
}

function isClientLike(value: unknown): value is ClientRecord {
  return (
    typeof value === "object" &&
    value !== null &&
    typeof (value as ClientRecord).id === "string" &&
    typeof (value as ClientRecord).displayName === "string"
  );
}

export function loadAllClients(): ClientRecord[] {
  const localOnly = readLocal().filter(
    (c) => !SEED_CLIENTS.some((s) => s.id === c.id),
  );
  return [...SEED_CLIENTS, ...localOnly];
}

export function getClient(id: string | null | undefined): ClientRecord | undefined {
  if (!id) return undefined;
  return loadAllClients().find((c) => c.id === id);
}

export function addClient(record: ClientRecord) {
  const existing = readLocal();
  if (SEED_CLIENTS.some((s) => s.id === record.id)) {
    throw new Error(`Client ID ${record.id} is reserved by the seed roster.`);
  }
  if (existing.some((c) => c.id === record.id)) {
    throw new Error(`Client ID ${record.id} already exists.`);
  }
  writeLocal([...existing, record]);
}

export function removeClient(id: string) {
  if (SEED_CLIENTS.some((s) => s.id === id)) {
    throw new Error("Seed clients cannot be removed.");
  }
  writeLocal(readLocal().filter((c) => c.id !== id));
}

export function nextClientId(existing: ClientRecord[]): string {
  let n = existing.length + 1;
  let id = `C${String(n).padStart(3, "0")}`;
  while (existing.some((c) => c.id === id)) {
    n += 1;
    id = `C${String(n).padStart(3, "0")}`;
  }
  return id;
}

// Legacy alias — kept so existing imports of `CLIENTS` continue to work.
// Represents the seed list only; use `loadAllClients()` or `useClients()` for
// the full reactive list.
export const CLIENTS = SEED_CLIENTS;

export function formatAUM(eur: number): string {
  if (eur >= 1_000_000_000) return `€${(eur / 1_000_000_000).toFixed(1)}B`;
  if (eur >= 1_000_000) return `€${(eur / 1_000_000).toFixed(1)}M`;
  if (eur >= 1_000) return `€${(eur / 1_000).toFixed(0)}K`;
  return `€${eur}`;
}
