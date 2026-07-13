import { fileURLToPath } from "node:url";

import { defineConfig } from "vitest/config";

// Alias "@/..." = ./src (mesmo mapeamento do tsconfig), para os testes poderem
// importar módulos da aplicação. Ambiente default = node (testes puros);
// testes de DOM declaram `// @vitest-environment jsdom` no topo do arquivo.
export default defineConfig({
  // O tsconfig do Next usa jsx:"preserve" (quem compila é o Next); nos testes
  // quem compila é o oxc do rolldown-vite — precisa do runtime automático do
  // React para conseguir importar componentes .tsx.
  oxc: { jsx: { runtime: "automatic" } },
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
});
