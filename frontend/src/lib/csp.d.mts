export function generateNonce(): string;
export function apiOrigin(apiUrl?: string | null): string | null;
export function buildContentSecurityPolicy(options?: {
  apiUrl?: string | null;
  dev?: boolean;
  nonce?: string;
}): string;
