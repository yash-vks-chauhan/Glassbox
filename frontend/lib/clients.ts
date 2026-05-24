// Phase D: client master data lives in the backend (GET/POST /clients),
// tenant-scoped behind the auth dependencies. The localStorage path is gone —
// callers either use the `useClients()` hook (client components) or
// `loadAllClients()` (server components / data fetching).
//
// The wire shape uses snake_case to match Pydantic; we convert to camelCase
// `ClientRecord` here so the rest of the frontend stays unchanged.

import { request } from "@/lib/api";

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

type ClientOutWire = {
  id: string;
  client_code: string;
  display_name: string;
  household: string | null;
  risk_profile: string;
  jurisdictions: string[];
  max_single_position_pct: number | null;
  min_liquid_within_30d_pct: number | null;
  excluded_sectors: string[];
  excluded_regions: string[];
  ips_version: string | null;
  ips_updated_at: string | null;
  aum_eur: number | null;
  advisor_name: string | null;
  created_at: string;
};

// In-app event used by the New Client dialog to ping live listeners (the
// `useClients` hook) so the roster re-fetches without a full page reload.
// Survives across Phase D because the hook-based refresh is still useful;
// the persistence behind it just moved server-side.
export const CHANGE_EVENT = "glassbox-clients-change";

function fromWire(c: ClientOutWire): ClientRecord {
  return {
    id: c.client_code,
    displayName: c.display_name,
    household: c.household ?? "",
    riskProfile: (c.risk_profile as RiskProfile) ?? "moderate",
    jurisdictions: c.jurisdictions ?? [],
    maxSinglePositionPct: c.max_single_position_pct ?? 0,
    minLiquidWithin30dPct: c.min_liquid_within_30d_pct ?? 0,
    excludedSectors: c.excluded_sectors ?? [],
    excludedRegions: c.excluded_regions ?? [],
    ipsVersion: c.ips_version ?? "",
    ipsUpdatedAt: c.ips_updated_at ? c.ips_updated_at.slice(0, 10) : "",
    aumEur: c.aum_eur ?? 0,
    advisor: c.advisor_name ?? "",
  };
}

export async function loadAllClients(): Promise<ClientRecord[]> {
  try {
    const rows = await request<ClientOutWire[]>("/clients");
    return rows.map(fromWire);
  } catch {
    return [];
  }
}

export async function getClient(
  id: string | null | undefined,
): Promise<ClientRecord | undefined> {
  if (!id) return undefined;
  try {
    const row = await request<ClientOutWire>(`/clients/${encodeURIComponent(id)}`);
    return fromWire(row);
  } catch {
    return undefined;
  }
}

export async function addClient(record: ClientRecord): Promise<ClientRecord> {
  const created = await request<ClientOutWire>("/clients", {
    method: "POST",
    body: JSON.stringify({
      client_code: record.id,
      display_name: record.displayName,
      household: record.household || null,
      risk_profile: record.riskProfile,
      jurisdictions: record.jurisdictions,
      max_single_position_pct: record.maxSinglePositionPct,
      min_liquid_within_30d_pct: record.minLiquidWithin30dPct,
      excluded_sectors: record.excludedSectors,
      excluded_regions: record.excludedRegions,
      ips_version: record.ipsVersion || null,
      ips_updated_at: record.ipsUpdatedAt || null,
      aum_eur: record.aumEur || null,
      advisor_name: record.advisor || null,
    }),
  });
  if (typeof window !== "undefined") {
    window.dispatchEvent(new Event(CHANGE_EVENT));
  }
  return fromWire(created);
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

export function formatAUM(eur: number): string {
  if (eur >= 1_000_000_000) return `€${(eur / 1_000_000_000).toFixed(1)}B`;
  if (eur >= 1_000_000) return `€${(eur / 1_000_000).toFixed(1)}M`;
  if (eur >= 1_000) return `€${(eur / 1_000).toFixed(0)}K`;
  return `€${eur}`;
}
