import { notFound } from "next/navigation";

export const metadata = {
  title: "Harness — fundação visual",
  robots: { index: false, follow: false },
};

// Harness = superfície interna de desenvolvimento; indisponível em produção.
// O import fica no ramo de desenvolvimento: no build de produção a condição
// vira constante, o ramo morto é descartado e o HarnessClient não entra no
// bundle (um import estático o empacotaria mesmo com a rota em 404).
export default async function HarnessPage() {
  if (process.env.NODE_ENV === "production") {
    notFound();
  } else {
    const { HarnessClient } = await import("./HarnessClient");
    return <HarnessClient />;
  }
}
