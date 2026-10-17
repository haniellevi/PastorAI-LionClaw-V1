import { authedFetch, readDetail } from "@/lib/dashboard-api";
export interface PrayerRequest {
  id: string;
  summary: string;
  pessoa_nome: string;
  audience: "pastoral" | "pastoral_lider";
  state: "open" | "assigned" | "closed";
  created_at: string;
  responsavel_id: string | null;
}
export async function prayerFetch<T>(
  token: string,
  path: string,
  init?: RequestInit,
): Promise<T> {
  const response = await authedFetch(token, `/prayer-requests${path}`, {
    ...init,
    cache: "no-store",
  });
  if (!response.ok)
    throw new Error(
      (await readDetail(response)) ?? "Não foi possível carregar os pedidos.",
    );
  return response.json() as Promise<T>;
}
