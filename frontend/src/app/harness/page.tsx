import { notFound } from "next/navigation";

import { HarnessClient } from "./HarnessClient";

export const metadata = { title: "Harness — fundação visual", robots: { index: false, follow: false } };

// Harness = superfície interna de desenvolvimento; indisponível em produção.
export default function HarnessPage() {
  if (process.env.NODE_ENV === "production") notFound();
  return <HarnessClient />;
}
