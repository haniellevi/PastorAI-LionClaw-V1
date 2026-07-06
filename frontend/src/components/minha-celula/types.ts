/** Toast leve (sucesso/erro) compartilhado pelas telas da Minha Célula. */
export interface CellToast {
  kind: "ok" | "err";
  text: string;
}

export type FlashToast = (toast: CellToast) => void;
