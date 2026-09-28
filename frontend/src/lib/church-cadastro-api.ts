import { SessionExpiredError } from "./api";
import { ApiError, authedFetch, isRecord } from "./dashboard-api";

export interface ChurchCadastro {
  enderecoInstitucional: string | null;
  horariosCulto: string | null;
}

function isOptionalText(value: unknown): value is string | null {
  return value === null || (typeof value === "string" && value.length <= 400);
}

function parseCadastro(value: unknown): ChurchCadastro {
  if (!isRecord(value) || !isOptionalText(value.enderecoInstitucional) ||
      !isOptionalText(value.horariosCulto)) {
    throw new ApiError(0, "Cadastro da igreja indisponível.");
  }
  return { enderecoInstitucional: value.enderecoInstitucional, horariosCulto: value.horariosCulto };
}

/** Consultada por montagem; nunca compartilhada entre sessões ou cacheada. */
export async function fetchChurchCadastroCapability(token: string, signal?: AbortSignal): Promise<boolean> {
  try {
    const response = await authedFetch(token, "/igreja/cadastro/capabilities", {
      cache: "no-store", signal,
    });
    if (!response.ok) return false;
    const body: unknown = await response.json();
    return isRecord(body) && body.version === 1;
  } catch (error) {
    if (error instanceof SessionExpiredError) throw error;
    return false;
  }
}

export async function getChurchCadastro(token: string, signal?: AbortSignal): Promise<ChurchCadastro> {
  const response = await authedFetch(token, "/igreja/cadastro", { cache: "no-store", signal });
  if (!response.ok) throw new ApiError(response.status, "Não foi possível carregar o cadastro da igreja.");
  return parseCadastro(await response.json());
}

export async function saveChurchCadastro(
  token: string, data: ChurchCadastro, signal?: AbortSignal,
): Promise<ChurchCadastro> {
  const payload = parseCadastro(data);
  const response = await authedFetch(token, "/igreja/cadastro", {
    method: "PUT", cache: "no-store", signal, body: JSON.stringify(payload),
  });
  if (!response.ok) throw new ApiError(response.status, "Não foi possível salvar o cadastro da igreja.");
  return parseCadastro(await response.json());
}
