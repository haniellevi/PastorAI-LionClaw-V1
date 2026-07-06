/** Toast leve (sucesso/erro) compartilhado pelas abas da Central de Célula. */
export interface CentralToast {
  kind: "ok" | "err";
  text: string;
}

export type FlashToast = (toast: CentralToast) => void;

/** Abas da Central (Jornada G12 > Discipular > Central de Célula). */
export type CentralTab =
  | "dashboard"
  | "cells"
  | "requests"
  | "notices"
  | "materials";
