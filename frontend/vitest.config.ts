import { fileURLToPath } from "node:url";

import { defineConfig } from "vitest/config";

// Alias "@/..." = ./src (mesmo mapeamento do tsconfig), para os testes poderem
// importar módulos da aplicação. Ambiente default = node (testes puros);
// testes de DOM declaram `// @vitest-environment jsdom` no topo do arquivo.
export default defineConfig({
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
});
