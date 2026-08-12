# Implementação local, Fatia 04: Operação Pastoral Guiada

Data: 2026-08-11

Status: `IMPLEMENTAÇÃO LOCAL, AGUARDANDO ACEITE VISUAL`

Base: `32951dd6d29ab977f9d02bc6e46ea7f28275c7bd`

Branch local: `codex/redesign-diamante-ui`

Grafo: `NÃO USADO`; a fatia foi definida por leitura direta do produto, dos
documentos de design, dos componentes ativos e por inspeção visual no navegador.

## Direção aprovada

O usuário aprovou a direção visual “Diamante Lapidado” para ser aplicada ao
sistema: marinho profundo no shell, azul mineral para ação, teal apenas como
sinal de avanço, superfícies claras e quentes e âmbar reservado a pendências
reais. A marca continua usando o diamante oficial da Igreja 12; nenhum símbolo
alternativo foi inventado.

A referência desta fatia foi a composição conceitual local de Minha Célula,
gerada fora do repositório. Ela orienta hierarquia, ritmo e comportamento, mas
não é fonte de verdade para texto, dados ou funcionalidades. Os ativos canônicos
continuam em `frontend/public/brand/` e em `assets/brand/`.

## Problema observado

A versão anterior de Minha Célula era funcional, mas apresentava todas as tarefas
em uma sequência longa de títulos, textos, cards e formulários. A reunião exigia
rolagem extensa antes da ação final e não deixava claro onde começar, o que já
foi concluído ou o que ainda precisava de atenção.

O redesenho não remove capacidades. Ele reduz a carga cognitiva por meio de duas
camadas de divulgação progressiva:

1. abas locais separam as áreas da célula;
2. o relatório abre uma etapa operacional por vez.

## Contrato visual implementado

### Contexto antes da operação

- cabeçalho compacto com nome, agenda, cobertura e total de membros;
- CTA `Planejar reunião` permanece visível sem competir com o relatório;
- o símbolo canônico aparece com as oito facetas legíveis na sidebar e em
  assinatura compacta no cabeçalho móvel do app;
- o diamante aparece como linguagem de progresso, não como decoração repetida.

### Arquitetura local de informação

As funções reais foram organizadas em seis abas:

1. Relatório;
2. Pessoas;
3. Avisos;
4. Materiais;
5. Solicitações;
6. Dados da célula.

Nenhuma rota, permissão, API ou regra de aprovação foi alterada por essa
organização.

### Relatório em quatro etapas

1. Presença;
2. Visitantes;
3. Registros;
4. Fechamento e envio.

Só uma etapa fica expandida. Os números, visitantes, registros, oferta e status
são derivados do relatório real. O progresso mostra a etapa atual e não afirma
que uma tarefa foi concluída sem evidência do backend.

### Resumo responsivo

- desktop: resumo lateral fixo durante a rolagem do relatório;
- tablet e celular: faixa compacta com etapa atual e informação principal;
- celular: ações de salvamento permanecem acima da navegação inferior;
- abas podem rolar horizontalmente sem provocar overflow na página.

### Linguagem e dados imperfeitos

- pendência usa âmbar e explica a próxima ação;
- envio concluído usa estado semântico de sucesso;
- um cadastro que contém apenas telefone aparece como `Contato sem nome`, com o
  número em segundo plano, em vez de tratar o telefone como nome de pessoa;
- nenhuma métrica, prazo ou confirmação fictícia foi adicionada.

## Acessibilidade incorporada

- cabeçalhos em ordem semântica;
- etapas com `aria-expanded`, `aria-controls` e regiões nomeadas;
- foco visível no acionador inteiro;
- controles operacionais com altura mínima de 44 px no mobile;
- status e progresso expostos a tecnologias assistivas;
- cores sem substituir texto, ícone ou estado;
- movimento limitado a cor, caret e barra de progresso, respeitando o contrato
  global de `prefers-reduced-motion`.

## Arquivos da fatia

- `frontend/src/components/minha-celula/MinhaCelulaLider.tsx`;
- `frontend/src/components/minha-celula/MeetingReportForm.tsx`;
- `frontend/src/components/minha-celula/AttendanceSection.tsx`;
- `frontend/src/components/minha-celula/VisitorsSection.tsx`;
- `frontend/src/components/minha-celula/RecordsSection.tsx`;
- `frontend/src/components/minha-celula/OfferingSection.tsx`;
- `frontend/src/components/minha-celula/SubmitReportButton.tsx`;
- `frontend/src/components/shell/Topbar.tsx`;
- `frontend/src/components/shell/Topbar.test.ts`;
- `frontend/src/app/globals.css`;
- `frontend/src/components/minha-celula/MeetingReportForm.flow.test.ts`.

## Evidência de validação

- typecheck do frontend;
- suíte completa do frontend;
- teste focal do fluxo com quatro etapas, abertura única, resumo real, estado
  pendente, estado enviado e fallback de contato sem nome;
- inspeção visual local em `360`, `390`, `768`, `1024` e `1440` px;
- verificação de ausência de overflow horizontal e de alvos de toque no celular;
- build de produção com Next.js `15.5.22`;
- `git diff --check`.

## Sequência recomendada para o sistema

A linguagem visual deve avançar em fatias verticais, sem uma troca global cega:

1. **Minha Célula:** operação guiada, implementada nesta fatia;
2. **Painel de Hoje:** transformar fila, contexto e Jornada G12 em prioridades
   visuais sem criar métricas;
3. **Conversas:** separar lista, contexto da pessoa, estado da IA e ação humana;
4. **Agenda:** distinguir semana, evento, confirmação e comunicação;
5. **Pessoas e Jornada G12:** reduzir tabelas longas e evidenciar próximo passo;
6. **Central, Configurações e Admin:** aplicar a mesma clareza com densidade
   compatível com tarefas administrativas.

Cada módulo deve reutilizar tokens, shell, estados e princípios desta fatia,
mas manter seu próprio fluxo de trabalho. A interface não deve virar uma coleção
de cards idênticos.

## Gates restantes

- aceite visual explícito da fatia em dados de demonstração;
- commit e PR separados;
- revisão independente e CI;
- merge separado;
- deploy separado;
- smoke autenticado por papel em produção.

Esta autorização não inclui commit, push, PR, merge ou produção.
