/**
 * Cache curto, somente em memória, para leituras autenticadas.
 *
 * A chave inclui o token da sessão, impedindo reaproveitamento entre usuários
 * ou tenants. Nada é persistido em localStorage/sessionStorage e cada resposta
 * é clonada antes de sair do cache, pois o body de Response é consumível uma vez.
 */

interface CacheEntry {
  expiresAt: number;
  response: Response;
  token: string;
  path: string;
}

export class AuthedResponseCache {
  private readonly entries = new Map<string, CacheEntry>();

  constructor(
    private readonly maxEntries = 64,
    private readonly now: () => number = Date.now,
  ) {}

  private key(token: string, path: string): string {
    return `${token}\u0000${path}`;
  }

  get(token: string, path: string): Response | null {
    const key = this.key(token, path);
    const entry = this.entries.get(key);
    if (!entry) return null;
    if (entry.expiresAt <= this.now()) {
      this.entries.delete(key);
      return null;
    }

    // Atualiza a ordem de inserção para uma política LRU simples.
    this.entries.delete(key);
    this.entries.set(key, entry);
    return entry.response.clone();
  }

  set(token: string, path: string, response: Response, ttlMs: number): void {
    if (!response.ok || ttlMs <= 0) return;
    const key = this.key(token, path);
    this.entries.delete(key);
    this.entries.set(key, {
      expiresAt: this.now() + ttlMs,
      response: response.clone(),
      token,
      path,
    });

    while (this.entries.size > this.maxEntries) {
      const oldest = this.entries.keys().next().value as string | undefined;
      if (!oldest) break;
      this.entries.delete(oldest);
    }
  }

  clear(token?: string, pathPrefixes?: string[]): void {
    if (!token) {
      this.entries.clear();
      return;
    }
    for (const [key, entry] of this.entries) {
      if (entry.token !== token) continue;
      if (
        pathPrefixes?.length &&
        !pathPrefixes.some((prefix) => entry.path.startsWith(prefix))
      ) {
        continue;
      }
      this.entries.delete(key);
    }
  }

  get size(): number {
    return this.entries.size;
  }
}
