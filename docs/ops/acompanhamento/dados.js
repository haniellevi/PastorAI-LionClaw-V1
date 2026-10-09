window.PAINEL_DADOS = {
 "gerado_em": "2026-10-09T13:26:58-03:00",
 "git": {
  "branch": "docs/passo0-regras-dev-online",
  "sha": "dcc99b47"
 },
 "repositorio": "haniellevi/PastorAI-LionClaw-V1",
 "plano": "docs/ops/refatoracao-modular-plano.md",
 "checks_obrigatorios": [
  "backend-tests",
  "frontend-ci",
  "e2e-critical",
  "rls-integration"
 ],
 "estados": {
  "futura": "Futura",
  "pronta": "Pronta",
  "em_andamento": "Em andamento",
  "em_validacao": "Em validação",
  "bloqueada": "Bloqueada",
  "concluida": "Concluída"
 },
 "indicadores": [
  "implementacao",
  "validacao_local",
  "ci",
  "integracao_main",
  "publicacao_dev",
  "publicacao_prod"
 ],
 "fases": [
  {
   "id": "PREP",
   "nome": "Preparação: dependências",
   "trilha": "principal",
   "ordem": 1,
   "secao": "Preparação inicial"
  },
  {
   "id": "F0D",
   "nome": "F0 · Documentação (#461)",
   "trilha": "principal",
   "ordem": 2,
   "secao": "F0"
  },
  {
   "id": "F0S",
   "nome": "F0 · Script test-local.sh",
   "trilha": "principal",
   "ordem": 3,
   "secao": "F0"
  },
  {
   "id": "F2A",
   "nome": "F2a · Transporte simulado (#462)",
   "trilha": "principal",
   "ordem": 4,
   "secao": "F2a"
  },
  {
   "id": "F1",
   "nome": "F1 · Validação do visitante",
   "trilha": "principal",
   "ordem": 5,
   "secao": "F1"
  },
  {
   "id": "F2B",
   "nome": "F2b · Prova integrada",
   "trilha": "principal",
   "ordem": 6,
   "secao": "F2b"
  },
  {
   "id": "F3",
   "nome": "F3 · DEV online",
   "trilha": "principal",
   "ordem": 7,
   "secao": "F3"
  },
  {
   "id": "F4",
   "nome": "F4 · Promoção e release",
   "trilha": "principal",
   "ordem": 8,
   "secao": "F4"
  },
  {
   "id": "F5",
   "nome": "F5 · Extração da resposta",
   "trilha": "principal",
   "ordem": 9,
   "secao": "F5"
  },
  {
   "id": "PAR",
   "nome": "Trilhas paralelas",
   "trilha": "paralela",
   "ordem": 10,
   "secao": "Seções 2 e 7"
  },
  {
   "id": "BKL",
   "nome": "Backlog condicionado",
   "trilha": "backlog",
   "ordem": 11,
   "secao": "Seção 6"
  }
 ],
 "tarefas": [
  {
   "id": "T01",
   "titulo": "Corrigir as dependências herdadas da main (PR #463)",
   "fase": "PREP",
   "trilha": "principal",
   "sequencia": 1,
   "estado": "em_validacao",
   "objetivo": "Fazer os audits de backend e frontend voltarem a passar, atualizando só o necessário: LangGraph 1.2.14 (prebuilt 1.1.0, SDK 0.4.6), sharp 0.35.5 e source-map-js 1.2.2.",
   "criterio_aceite": [
    "Audits e quatro checks aprovados no candidato, sem desativar verificações nem atribuir PASS a suites que não rodaram.",
    "Depois de integrar, #461 e #462 recebem a nova base e são revalidados."
   ],
   "depende_de": [],
   "aguardando": "Integração na main: depende da autorização do proprietário. Esta execução não faz merge.",
   "proxima_acao": "Aguardando sua aprovação do merge do #463 (escopo na resposta da sessão). Depois: atualizar a base de #461, #464 e #462 e revalidar.",
   "responsavel": "proprietário (autorizar integração)",
   "pr": [
    463
   ],
   "pr_referencia": 463,
   "indicadores": {
    "implementacao": {
     "status": "ok",
     "nota": "Commit 9f61ba5e no PR #463."
    },
    "validacao_local": {
     "status": "ok",
     "nota": "pip-audit limpo nos dois locks; pytest -m \"not rls_integration\" verde; npm audit --omit=dev, lint, tsc, 1.165 testes, next build e smoke de headers verdes. Imagem Docker e rls_integration não foram reproduzidos localmente."
    },
    "integracao_main": {
     "status": "pendente",
     "nota": "PR aberto, não integrado.",
     "origem": "github",
     "consultado_em": "2026-10-09T13:26:54-03:00"
    },
    "publicacao_dev": {
     "status": "nao_aplicavel",
     "nota": "O DEV online ainda não existe."
    },
    "publicacao_prod": {
     "status": "pendente",
     "nota": "Sem evidência de publicação. Dependências chegam a PROD só em release."
    },
    "ci": {
     "status": "ok",
     "nota": "4 de 4 checks obrigatórios aprovados.",
     "origem": "github",
     "consultado_em": "2026-10-09T13:26:54-03:00"
    }
   },
   "evidencias": [
    {
     "data": "2026-10-09",
     "tipo": "pr",
     "descricao": "PR #463 aberto sobre a base d36ab813.",
     "url": "https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/463",
     "sha": "9f61ba5e087b60d4336d21ed2d025996dff2cdc3"
    },
    {
     "data": "2026-10-09",
     "tipo": "ci",
     "descricao": "Checks do PR: backend-tests, frontend-ci, e2e-critical, rls-integration e tooling-static aprovados (leitura do GitHub).",
     "url": "https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/463/checks"
    },
    {
     "data": "2026-10-09",
     "tipo": "local",
     "descricao": "Verificação local registrada na descrição do PR e na sprint docs/sprints/2026-10-09-dependencias-audit.md (branch do #463)."
    },
    {
     "data": "2026-10-09",
     "tipo": "limite",
     "descricao": "npm audit com --omit=dev aprovado não significa zero vulnerabilidades no grafo completo: npm ci do candidato relata 11 (3 moderadas, 8 altas), contra 13 (3 moderadas, 10 altas) na base. A triagem das oito altas é a tarefa S4."
    },
    {
     "data": "2026-10-09",
     "tipo": "revisao",
     "descricao": "Preparo da integração, reconferido em 09/10: #463 aberto, não rascunho, MERGEABLE/CLEAN, head 9f61ba5e, base e main em d36ab813; 5 arquivos (backend/requirements.txt e .lock, frontend/package.json e package-lock.json, sprint), +176/−162; backend-tests, frontend-ci, e2e-critical, rls-integration, tooling-static e Vercel em SUCCESS. Efeitos do merge na main: reexecuta os 5 workflows de CI (push em main) e, pelo histórico do PRODUCTION-RUNBOOK, a Vercel publica Production do frontend automaticamente (muda sharp/source-map-js no build). O backend não é publicado: backend-deploy-manual.yml só roda por workflow_dispatch; requirements.lock só chega a PROD num release manual. reviewDecision vazio; proteção da branch não verificada."
    }
   ],
   "prs": [
    {
     "numero": 463,
     "url": "https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/463",
     "github": {
      "ok": true,
      "consultado_em": "2026-10-09T13:26:54-03:00",
      "tentativa_em": "2026-10-09T13:26:54-03:00",
      "erro": null,
      "dados": {
       "numero": 463,
       "titulo": "fix: atualizar dependências reprovadas pelos audits",
       "url": "https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/463",
       "estado": "OPEN",
       "rascunho": false,
       "criado_em": "2026-10-09T14:32:46Z",
       "atualizado_em": "2026-10-09T14:33:30Z",
       "integrado_em": null,
       "branch": "fix/deps-audit-20261009",
       "base": "main",
       "sha": "9f61ba5e087b60d4336d21ed2d025996dff2cdc3",
       "sha_base": "d36ab813bf45f8bc92fd605425394570e85ad3ec",
       "mergeavel": "MERGEABLE",
       "revisao": "",
       "checks": [
        {
         "nome": "backend-tests",
         "status": "COMPLETED",
         "conclusao": "SUCCESS",
         "url": "https://github.com/haniellevi/PastorAI-LionClaw-V1/actions/runs/37944984761/job/113868823091"
        },
        {
         "nome": "e2e-critical",
         "status": "COMPLETED",
         "conclusao": "SUCCESS",
         "url": "https://github.com/haniellevi/PastorAI-LionClaw-V1/actions/runs/37944984708/job/113868824514"
        },
        {
         "nome": "frontend-ci",
         "status": "COMPLETED",
         "conclusao": "SUCCESS",
         "url": "https://github.com/haniellevi/PastorAI-LionClaw-V1/actions/runs/37944984799/job/113868824569"
        },
        {
         "nome": "rls-integration",
         "status": "COMPLETED",
         "conclusao": "SUCCESS",
         "url": "https://github.com/haniellevi/PastorAI-LionClaw-V1/actions/runs/37944984710/job/113868822541"
        },
        {
         "nome": "tooling-static",
         "status": "COMPLETED",
         "conclusao": "SUCCESS",
         "url": "https://github.com/haniellevi/PastorAI-LionClaw-V1/actions/runs/37944984775/job/113868823007"
        },
        {
         "nome": "Vercel",
         "status": "SUCCESS",
         "conclusao": null,
         "url": "https://vercel.com/raniel-levis-projects/pastorai-frontend-prod/hQFPqJ62qCnqHzWEqn1L3wBZLQtA"
        },
        {
         "nome": "Vercel Preview Comments",
         "status": "COMPLETED",
         "conclusao": "SUCCESS",
         "url": "https://vercel.com/github"
        }
       ]
      }
     }
    }
   ],
   "dependencias_abertas": [],
   "executavel": false,
   "situacao": "Validado — aguardando integração",
   "estado_rotulo": "Em validação"
  },
  {
   "id": "T02",
   "titulo": "Plano consolidado e painel de acompanhamento (PR #461)",
   "fase": "F0D",
   "trilha": "principal",
   "sequencia": 2,
   "estado": "em_validacao",
   "objetivo": "Substituir o plano versionado do #461 pelo plano consolidado, alinhar AGENTS, CLAUDE, MVP e sprint, e criar o painel de acompanhamento.",
   "criterio_aceite": [
    "docs/ops/refatoracao-modular-plano.md contém o plano consolidado, com links portáveis e DEV descrito como planejado.",
    "AGENTS.md traz o procedimento curto de atualização; CLAUDE.md, MVP e sprint do Passo 0 coerentes.",
    "Painel abre a partir dos arquivos entregues e é regenerado por ./acompanhar.sh."
   ],
   "depende_de": [],
   "aguardando": "CI do PR: backend-tests e frontend-ci reprovam por audits herdados da main até a base ser atualizada (T03).",
   "proxima_acao": "Revisar o diff do #461. A reprovação por audits desaparece quando T01 for integrado e a base atualizada (T03).",
   "responsavel": "Claude (entrega) · proprietário (revisão)",
   "pr": [
    461
   ],
   "pr_referencia": 461,
   "indicadores": {
    "implementacao": {
     "status": "ok",
     "nota": "Plano, painel, comando e instruções no branch do #461."
    },
    "validacao_local": {
     "status": "ok",
     "nota": "Verificações do gerador (python3 docs/ops/acompanhamento/atualizar.py --verificar) e conferência visual no navegador em desktop e celular. Sem suites de produto: a mudança é só documentação e ferramenta de acompanhamento."
    },
    "integracao_main": {
     "status": "pendente",
     "nota": "PR aberto, não integrado.",
     "origem": "github",
     "consultado_em": "2026-10-09T13:26:52-03:00"
    },
    "publicacao_dev": {
     "status": "nao_aplicavel",
     "nota": "Documentação."
    },
    "publicacao_prod": {
     "status": "nao_aplicavel",
     "nota": "Documentação."
    },
    "ci": {
     "status": "falhou",
     "nota": "Reprovados: backend-tests, frontend-ci. Aprovados: 2 de 4 checks obrigatórios.",
     "origem": "github",
     "consultado_em": "2026-10-09T13:26:52-03:00"
    }
   },
   "evidencias": [
    {
     "data": "2026-10-09",
     "tipo": "pr",
     "descricao": "PR #461 aberto sobre a base d36ab813, com o plano anterior.",
     "url": "https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/461",
     "sha": "bed02fabfb43588e2fa7963727f5d4b9ee96a28c"
    },
    {
     "data": "2026-10-09",
     "tipo": "ci",
     "descricao": "No SHA bed02fab, e2e-critical, rls-integration e tooling-static passaram; backend-tests e frontend-ci falharam nos audits de dependências herdadas.",
     "url": "https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/461/checks"
    },
    {
     "data": "2026-10-09",
     "tipo": "local",
     "descricao": "Painel verificado em navegador: abas, filtros, detalhes e links, em 1280 px e 375 px sem rolagem horizontal; abre também direto do arquivo (file://, Chrome headless: 22 cartões renderizados). Falha simulada do gh preservou a última evidência como desatualizada; o validador recusou tarefa concluída sem evidência. Plano sem links locais da revisão (grep). Sem suites de produto: mudança só de documentação e ferramenta."
    }
   ],
   "pendencia_externa": "Resíduo Neon no guia local não rastreado docs/ops/CONFIGURACAO-DESENVOLVIMENTO.md:125 (arquivo do proprietário, fora do Git). Não alterado por esta entrega.",
   "prs": [
    {
     "numero": 461,
     "url": "https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/461",
     "github": {
      "ok": true,
      "consultado_em": "2026-10-09T13:26:52-03:00",
      "tentativa_em": "2026-10-09T13:26:52-03:00",
      "erro": null,
      "dados": {
       "numero": 461,
       "titulo": "docs: consolidar regras em AGENTS.md e adotar DEV online (Passo 0)",
       "url": "https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/461",
       "estado": "OPEN",
       "rascunho": false,
       "criado_em": "2026-10-09T12:41:49Z",
       "atualizado_em": "2026-10-09T16:05:03Z",
       "integrado_em": null,
       "branch": "docs/passo0-regras-dev-online",
       "base": "main",
       "sha": "a242b751379a93b37f04933b077e7016c54b0494",
       "sha_base": "d36ab813bf45f8bc92fd605425394570e85ad3ec",
       "mergeavel": "MERGEABLE",
       "revisao": "",
       "checks": [
        {
         "nome": "backend-tests",
         "status": "COMPLETED",
         "conclusao": "FAILURE",
         "url": "https://github.com/haniellevi/PastorAI-LionClaw-V1/actions/runs/37956428263/job/113908001428"
        },
        {
         "nome": "frontend-ci",
         "status": "COMPLETED",
         "conclusao": "FAILURE",
         "url": "https://github.com/haniellevi/PastorAI-LionClaw-V1/actions/runs/37956428391/job/113908001855"
        },
        {
         "nome": "e2e-critical",
         "status": "COMPLETED",
         "conclusao": "SUCCESS",
         "url": "https://github.com/haniellevi/PastorAI-LionClaw-V1/actions/runs/37956428341/job/113908001733"
        },
        {
         "nome": "rls-integration",
         "status": "COMPLETED",
         "conclusao": "SUCCESS",
         "url": "https://github.com/haniellevi/PastorAI-LionClaw-V1/actions/runs/37956428306/job/113908002018"
        },
        {
         "nome": "tooling-static",
         "status": "COMPLETED",
         "conclusao": "SUCCESS",
         "url": "https://github.com/haniellevi/PastorAI-LionClaw-V1/actions/runs/37956428272/job/113908001869"
        },
        {
         "nome": "Vercel",
         "status": "SUCCESS",
         "conclusao": null,
         "url": "https://vercel.com/raniel-levis-projects/pastorai-frontend-prod/FkryHQawtFqGHRTX2FQa7ecQPejp"
        },
        {
         "nome": "Vercel Preview Comments",
         "status": "COMPLETED",
         "conclusao": "SUCCESS",
         "url": "https://vercel.com/github"
        }
       ]
      }
     }
    }
   ],
   "dependencias_abertas": [],
   "executavel": false,
   "situacao": "Em validação — CI reprovado",
   "estado_rotulo": "Em validação"
  },
  {
   "id": "T03",
   "titulo": "Atualizar a base do #461 e revalidar",
   "fase": "F0D",
   "trilha": "principal",
   "sequencia": 3,
   "estado": "bloqueada",
   "objetivo": "Levar o #461 para a main que contém o #463 e confirmar os quatro checks no novo SHA.",
   "criterio_aceite": [
    "Branch do #461 atualizada sobre a main com o #463 integrado, sem perder as mudanças do proprietário.",
    "backend-tests, frontend-ci, e2e-critical e rls-integration aprovados no novo SHA."
   ],
   "depende_de": [
    "T01"
   ],
   "bloqueio": "O #463 ainda não foi integrado (aguarda autorização do proprietário).",
   "proxima_acao": "Depois da integração do #463: atualizar a base do #461 (merge ou rebase da main), enviar e conferir os checks.",
   "responsavel": "Claude",
   "pr": [
    461
   ],
   "pr_referencia": null,
   "indicadores": {
    "implementacao": {
     "status": "nao_iniciado",
     "nota": ""
    },
    "validacao_local": {
     "status": "nao_iniciado",
     "nota": ""
    },
    "integracao_main": {
     "status": "pendente",
     "nota": ""
    },
    "publicacao_dev": {
     "status": "nao_aplicavel",
     "nota": "Documentação."
    },
    "publicacao_prod": {
     "status": "nao_aplicavel",
     "nota": "Documentação."
    },
    "ci": {
     "status": "nao_iniciado",
     "nota": "Sem PR de referência ainda."
    }
   },
   "evidencias": [],
   "prs": [
    {
     "numero": 461,
     "url": "https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/461",
     "github": {
      "ok": true,
      "consultado_em": "2026-10-09T13:26:52-03:00",
      "tentativa_em": "2026-10-09T13:26:52-03:00",
      "erro": null,
      "dados": {
       "numero": 461,
       "titulo": "docs: consolidar regras em AGENTS.md e adotar DEV online (Passo 0)",
       "url": "https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/461",
       "estado": "OPEN",
       "rascunho": false,
       "criado_em": "2026-10-09T12:41:49Z",
       "atualizado_em": "2026-10-09T16:05:03Z",
       "integrado_em": null,
       "branch": "docs/passo0-regras-dev-online",
       "base": "main",
       "sha": "a242b751379a93b37f04933b077e7016c54b0494",
       "sha_base": "d36ab813bf45f8bc92fd605425394570e85ad3ec",
       "mergeavel": "MERGEABLE",
       "revisao": "",
       "checks": [
        {
         "nome": "backend-tests",
         "status": "COMPLETED",
         "conclusao": "FAILURE",
         "url": "https://github.com/haniellevi/PastorAI-LionClaw-V1/actions/runs/37956428263/job/113908001428"
        },
        {
         "nome": "frontend-ci",
         "status": "COMPLETED",
         "conclusao": "FAILURE",
         "url": "https://github.com/haniellevi/PastorAI-LionClaw-V1/actions/runs/37956428391/job/113908001855"
        },
        {
         "nome": "e2e-critical",
         "status": "COMPLETED",
         "conclusao": "SUCCESS",
         "url": "https://github.com/haniellevi/PastorAI-LionClaw-V1/actions/runs/37956428341/job/113908001733"
        },
        {
         "nome": "rls-integration",
         "status": "COMPLETED",
         "conclusao": "SUCCESS",
         "url": "https://github.com/haniellevi/PastorAI-LionClaw-V1/actions/runs/37956428306/job/113908002018"
        },
        {
         "nome": "tooling-static",
         "status": "COMPLETED",
         "conclusao": "SUCCESS",
         "url": "https://github.com/haniellevi/PastorAI-LionClaw-V1/actions/runs/37956428272/job/113908001869"
        },
        {
         "nome": "Vercel",
         "status": "SUCCESS",
         "conclusao": null,
         "url": "https://vercel.com/raniel-levis-projects/pastorai-frontend-prod/FkryHQawtFqGHRTX2FQa7ecQPejp"
        },
        {
         "nome": "Vercel Preview Comments",
         "status": "COMPLETED",
         "conclusao": "SUCCESS",
         "url": "https://vercel.com/github"
        }
       ]
      }
     }
    }
   ],
   "dependencias_abertas": [
    "T01"
   ],
   "executavel": false,
   "situacao": "Bloqueada",
   "estado_rotulo": "Bloqueada"
  },
  {
   "id": "T04",
   "titulo": "test-local.sh rejeita alvo desconhecido",
   "fase": "F0S",
   "trilha": "principal",
   "sequencia": 4,
   "estado": "em_validacao",
   "objetivo": "Hoje um alvo inexistente retorna 0 sem rodar testes. O script deve falhar de forma clara antes de executar qualquer ferramenta, mantendo todos, backend e frontend.",
   "criterio_aceite": [
    "Comando inválido sai com código diferente de zero e mensagem compreensível.",
    "Comandos válidos preservam seleção e versões (Python 3.13, Node 24, umask 022).",
    "Sem CLI nova: encaminhamento de argumentos e seleção rápida ficam para depois."
   ],
   "depende_de": [],
   "integra_apos": [
    "T01"
   ],
   "proxima_acao": "Após o #463 entrar na main, atualizar a base do #464 e revalidar os quatro checks.",
   "responsavel": "Claude",
   "pr": [
    464
   ],
   "pr_referencia": 464,
   "indicadores": {
    "implementacao": {
     "status": "ok",
     "nota": "Commit 18cef626 no PR #464 (test-local.sh + teste + sprint)."
    },
    "validacao_local": {
     "status": "parcial",
     "nota": "Reprodução antes/depois do alvo inválido e pytest tests/test_test_local_script.py (2 passed). Suíte completa e ruff não executados; CI do PR pendente."
    },
    "integracao_main": {
     "status": "pendente",
     "nota": "PR aberto, não integrado.",
     "origem": "github",
     "consultado_em": "2026-10-09T13:26:55-03:00"
    },
    "publicacao_dev": {
     "status": "nao_aplicavel",
     "nota": "Ferramenta local."
    },
    "publicacao_prod": {
     "status": "nao_aplicavel",
     "nota": "Ferramenta local."
    },
    "ci": {
     "status": "falhou",
     "nota": "Reprovados: backend-tests, frontend-ci. Aprovados: 2 de 4 checks obrigatórios.",
     "origem": "github",
     "consultado_em": "2026-10-09T13:26:55-03:00"
    }
   },
   "evidencias": [
    {
     "data": "2026-10-09",
     "tipo": "revisao",
     "descricao": "A revisão reproduziu que o script atual retorna 0 sem testes para alvo inexistente (relato da revisão; não repetido nesta execução)."
    },
    {
     "data": "2026-10-09",
     "tipo": "local",
     "descricao": "Reprodução: test-local.sh de origin/main com alvo 'bakend' saiu 0 sem rodar nada; com a correção saiu 2 com a mensagem 'Alvo desconhecido'. pytest tests/test_test_local_script.py: 2 passed. Suíte completa e ruff não rodaram localmente."
    },
    {
     "data": "2026-10-09",
     "tipo": "pr",
     "descricao": "PR #464 aberto sobre origin/main d36ab813 (branch fix/test-local-alvo-desconhecido).",
     "url": "https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/464",
     "sha": "18cef626"
    },
    {
     "data": "2026-10-09",
     "tipo": "ci",
     "descricao": "backend-tests e frontend-ci reprovaram só no passo de audit, antes das suites: pip-audit aponta langgraph-sdk 0.3.15 (CVE-2026-104873) e npm audit --omit=dev aponta sharp (3 altas). São as dependências herdadas da main que o #463 corrige; o diff do #464 não toca manifests. e2e-critical e rls-integration: ver painel/GitHub.",
     "url": "https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/464/checks"
    }
   ],
   "aguardando": "Integração do #463 (corrige os audits), depois rebase/revalidação do #464 e autorização do proprietário. Esta execução não faz merge.",
   "prs": [
    {
     "numero": 464,
     "url": "https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/464",
     "github": {
      "ok": true,
      "consultado_em": "2026-10-09T13:26:55-03:00",
      "tentativa_em": "2026-10-09T13:26:55-03:00",
      "erro": null,
      "dados": {
       "numero": 464,
       "titulo": "fix: test-local.sh rejeita alvo desconhecido",
       "url": "https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/464",
       "estado": "OPEN",
       "rascunho": false,
       "criado_em": "2026-10-09T16:07:47Z",
       "atualizado_em": "2026-10-09T16:08:29Z",
       "integrado_em": null,
       "branch": "fix/test-local-alvo-desconhecido",
       "base": "main",
       "sha": "18cef6267801955da657403b4f96780f3a22aa8d",
       "sha_base": "d36ab813bf45f8bc92fd605425394570e85ad3ec",
       "mergeavel": "MERGEABLE",
       "revisao": "",
       "checks": [
        {
         "nome": "backend-tests",
         "status": "COMPLETED",
         "conclusao": "FAILURE",
         "url": "https://github.com/haniellevi/PastorAI-LionClaw-V1/actions/runs/37956848484/job/113909423818"
        },
        {
         "nome": "frontend-ci",
         "status": "COMPLETED",
         "conclusao": "FAILURE",
         "url": "https://github.com/haniellevi/PastorAI-LionClaw-V1/actions/runs/37956848356/job/113909423903"
        },
        {
         "nome": "e2e-critical",
         "status": "COMPLETED",
         "conclusao": "SUCCESS",
         "url": "https://github.com/haniellevi/PastorAI-LionClaw-V1/actions/runs/37956848321/job/113909422283"
        },
        {
         "nome": "rls-integration",
         "status": "COMPLETED",
         "conclusao": "SUCCESS",
         "url": "https://github.com/haniellevi/PastorAI-LionClaw-V1/actions/runs/37956848343/job/113909422716"
        },
        {
         "nome": "tooling-static",
         "status": "COMPLETED",
         "conclusao": "SUCCESS",
         "url": "https://github.com/haniellevi/PastorAI-LionClaw-V1/actions/runs/37956848332/job/113909422696"
        },
        {
         "nome": "Vercel",
         "status": "SUCCESS",
         "conclusao": null,
         "url": "https://vercel.com/raniel-levis-projects/pastorai-frontend-prod/BJuZiP1DKFnXyWZcPQU4gNgbxhNH"
        },
        {
         "nome": "Vercel Preview Comments",
         "status": "COMPLETED",
         "conclusao": "SUCCESS",
         "url": "https://vercel.com/github"
        }
       ]
      }
     }
    }
   ],
   "dependencias_abertas": [],
   "executavel": false,
   "situacao": "Em validação — CI reprovado",
   "estado_rotulo": "Em validação"
  },
  {
   "id": "T05",
   "titulo": "Concluir o transporte simulado (correções do PR #462)",
   "fase": "F2A",
   "trilha": "principal",
   "sequencia": 5,
   "estado": "em_andamento",
   "objetivo": "Corrigir o validador de destinos e o estado do fake e ajustar descrições do candidato, concluindo F2a: Evolution falsa, chat e WHATSAPP_TRANSPORTE=simulado.",
   "criterio_aceite": [
    "URL adversarial recusada nos dois sentidos (127.example.invalid, 0x7f000001, 2130706433, 167772161, IPv4 não loopback, nomes fora da lista).",
    "APP_ENV=production recusa simulação; chave real não reutilizada.",
    "Fake: instância excluída permanece offline até recriação; sendMedia respeita desconexão ou sai do contrato.",
    "Webhook autenticado e segredo incorreto recusado; texto e erro programado observados no fake; transporte real preservado.",
    "BREVO_SEND_MODE=off exigido na configuração sintética; texto do PR, docstring, sprint, guia e checklist MVP sem alegar turno completo, RLS ou envio da outbox."
   ],
   "depende_de": [],
   "proxima_acao": "Fatia 2 (local): exclusão de instância deve ficar offline/ausente até recriação e endpoints (inclusive mídia) respeitarem a desconexão. Depois: gates por chamador e descrições. Atualizar a base do #462 só depois do #463 integrado; push no #462 só com autorização.",
   "responsavel": "Claude",
   "pr": [
    462
   ],
   "pr_referencia": 462,
   "indicadores": {
    "implementacao": {
     "status": "parcial",
     "nota": "Fatia 1 (validador de destino) pronta no commit local 0ffcb754 da branch local/t05-f2a-correcoes (worktree t05-f2a), sobre o head 08e89282 do #462. Pendentes: estado do fake na exclusão/mídia, gates por chamador, corpo do PR/docstring/sprint/guia/checklist. Sem push."
    },
    "validacao_local": {
     "status": "parcial",
     "nota": "tests/test_whatsapp_simulado.py: 57 passed no commit local 0ffcb754. test_whatsapp_simulado_turno_pg.py (PostgreSQL) e a suíte completa não rodaram."
    },
    "integracao_main": {
     "status": "pendente",
     "nota": "PR aberto, não integrado.",
     "origem": "github",
     "consultado_em": "2026-10-09T13:26:53-03:00"
    },
    "publicacao_dev": {
     "status": "nao_aplicavel",
     "nota": "O DEV online ainda não existe."
    },
    "publicacao_prod": {
     "status": "nao_aplicavel",
     "nota": "O modo simulado é recusado em production."
    },
    "ci": {
     "status": "falhou",
     "nota": "Reprovados: backend-tests, frontend-ci. Aprovados: 2 de 4 checks obrigatórios.",
     "origem": "github",
     "consultado_em": "2026-10-09T13:26:53-03:00"
    }
   },
   "evidencias": [
    {
     "data": "2026-10-09",
     "tipo": "pr",
     "descricao": "PR #462 aberto com o candidato de simulador.",
     "url": "https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/462",
     "sha": "08e8928216da35040b3d3cc5f08edb9ca62d3b8b"
    },
    {
     "data": "2026-10-09",
     "tipo": "revisao",
     "descricao": "Revisão reproduziu sem rede: o validador aceita hostnames iniciados por 127. e formas IPv4 numéricas; a exclusão de instância volta a significar open."
    },
    {
     "data": "2026-10-09",
     "tipo": "ci",
     "descricao": "Quatro testes novos aprovados dentro de 866 no job rls-integration (execução 37936670113); backend-tests e frontend-ci reprovados nos audits herdados.",
     "url": "https://github.com/haniellevi/PastorAI-LionClaw-V1/actions/runs/37936670113"
    },
    {
     "data": "2026-10-09",
     "tipo": "revisao",
     "descricao": "Dependência reclassificada: T01 não é necessária para desenvolver e testar as correções da F2a (código, testes e docs do #462 independem das versões de LangGraph/sharp). T01 só é exigida para integrar, porque os audits do CI reprovam sem ela. Por isso depende_de passou a [] e integra_apos a [T01], como na T04. T07 continua dependendo de T05 por necessidade técnica (usa o fake corrigido)."
    },
    {
     "data": "2026-10-09",
     "tipo": "local",
     "descricao": "Fatia 1 da F2a: is_internal_service_url substituída por is_simulated_destination(url, nomes) em backend/app/config.py, usada nos dois sentidos (backend→Evolution falsa: localhost, simulador-whatsapp; simulador→webhook: localhost, backend). IP literal exige ipaddress.is_loopback; outros nomes só por lista exata; recusa credenciais embutidas, porta inválida/0, 127.example.invalid, 0x7f000001, 2130706433, 167772161, IPv4 não loopback e o nome do outro sentido. 57 testes passaram em test_whatsapp_simulado.py (venv do checkout principal). Commit local 0ffcb754, não enviado.",
     "sha": "0ffcb754"
    }
   ],
   "integra_apos": [
    "T01"
   ],
   "prs": [
    {
     "numero": 462,
     "url": "https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/462",
     "github": {
      "ok": true,
      "consultado_em": "2026-10-09T13:26:53-03:00",
      "tentativa_em": "2026-10-09T13:26:53-03:00",
      "erro": null,
      "dados": {
       "numero": 462,
       "titulo": "feat: simulador de WhatsApp com transporte simulado (Fatia 1)",
       "url": "https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/462",
       "estado": "OPEN",
       "rascunho": false,
       "criado_em": "2026-10-09T13:24:54Z",
       "atualizado_em": "2026-10-09T13:25:39Z",
       "integrado_em": null,
       "branch": "feat/simulador-whatsapp",
       "base": "main",
       "sha": "08e8928216da35040b3d3cc5f08edb9ca62d3b8b",
       "sha_base": "d36ab813bf45f8bc92fd605425394570e85ad3ec",
       "mergeavel": "MERGEABLE",
       "revisao": "",
       "checks": [
        {
         "nome": "backend-tests",
         "status": "COMPLETED",
         "conclusao": "FAILURE",
         "url": "https://github.com/haniellevi/PastorAI-LionClaw-V1/actions/runs/37936670182/job/113840332981"
        },
        {
         "nome": "frontend-ci",
         "status": "COMPLETED",
         "conclusao": "FAILURE",
         "url": "https://github.com/haniellevi/PastorAI-LionClaw-V1/actions/runs/37936670249/job/113840332008"
        },
        {
         "nome": "e2e-critical",
         "status": "COMPLETED",
         "conclusao": "SUCCESS",
         "url": "https://github.com/haniellevi/PastorAI-LionClaw-V1/actions/runs/37936670153/job/113840332009"
        },
        {
         "nome": "rls-integration",
         "status": "COMPLETED",
         "conclusao": "SUCCESS",
         "url": "https://github.com/haniellevi/PastorAI-LionClaw-V1/actions/runs/37936670113/job/113840331677"
        },
        {
         "nome": "tooling-static",
         "status": "COMPLETED",
         "conclusao": "SUCCESS",
         "url": "https://github.com/haniellevi/PastorAI-LionClaw-V1/actions/runs/37936670338/job/113840332669"
        },
        {
         "nome": "Vercel",
         "status": "SUCCESS",
         "conclusao": null,
         "url": "https://vercel.com/raniel-levis-projects/pastorai-frontend-prod/3swkFeQvMDbj1yZPkjBUcDECe7VG"
        },
        {
         "nome": "Vercel Preview Comments",
         "status": "COMPLETED",
         "conclusao": "SUCCESS",
         "url": "https://vercel.com/github"
        }
       ]
      }
     }
    }
   ],
   "dependencias_abertas": [],
   "executavel": false,
   "situacao": "Em andamento",
   "estado_rotulo": "Em andamento"
  },
  {
   "id": "T06",
   "titulo": "Extrair a validação do nome do visitante para o domínio",
   "fase": "F1",
   "trilha": "principal",
   "sequencia": 6,
   "estado": "futura",
   "objetivo": "Mover canonical_visitor_name e um erro puro para um módulo de domínio, atualizando propostas, serviço ministerial e o parser do catálogo.",
   "criterio_aceite": [
    "O serviço ministerial deixa de importar propostas do agente.",
    "Entradas aceitas e recusadas iguais (tipo estrito, trim, limite, Unicode/controles, privacidade do erro); fluxos de proposta e SIM iguais.",
    "ProposalContractError e HTTP 422 mantidos nas bordas; sem migration, schema, flags, locks ou autorização alterados."
   ],
   "depende_de": [
    "T05"
   ],
   "proxima_acao": "Segue a T05 por ordem do plano (uma fatia por vez), não por necessidade técnica. Pode ser desenvolvida em ramo próprio a partir da main; integra depois do #463.",
   "responsavel": "Claude",
   "pr": [],
   "pr_referencia": null,
   "indicadores": {
    "implementacao": {
     "status": "nao_iniciado",
     "nota": ""
    },
    "validacao_local": {
     "status": "nao_iniciado",
     "nota": ""
    },
    "integracao_main": {
     "status": "pendente",
     "nota": ""
    },
    "publicacao_dev": {
     "status": "nao_aplicavel",
     "nota": "O DEV online ainda não existe."
    },
    "publicacao_prod": {
     "status": "pendente",
     "nota": "Chega a PROD só em release."
    },
    "ci": {
     "status": "nao_iniciado",
     "nota": "Sem PR de referência ainda."
    }
   },
   "evidencias": [
    {
     "data": "2026-10-09",
     "tipo": "revisao",
     "descricao": "depende_de ajustado: antes T01 (só espera de merge do #463); agora T05, que reflete a sequência única do plano. A extração pura do visitante não depende tecnicamente do simulador nem do #463; só a integração exige T01 (integra_apos)."
    }
   ],
   "integra_apos": [
    "T01"
   ],
   "prs": [],
   "dependencias_abertas": [
    "T05"
   ],
   "executavel": false,
   "situacao": "Futura",
   "estado_rotulo": "Futura"
  },
  {
   "id": "T07",
   "titulo": "Prova integrada: Redis real, RLS real e uma ação vertical",
   "fase": "F2B",
   "trilha": "principal",
   "sequencia": 7,
   "estado": "futura",
   "objetivo": "Percorrer webhook autenticado, Redis, worker (em thread, no mesmo processo), catálogo e autorização reais, serviço, banco com policies e leitura pela API, começando pelo visitante.",
   "criterio_aceite": [
    "Ação autorizada e recusada sem papel; dois tenants com controles positivos e recusa cruzada sob policies reais.",
    "Consentimento e opt-out; replay sem efeito duplicado; revogação entre proposta e SIM; falha antes do commit com efeito e recibo atômicos.",
    "Resposta recebida no fake e visível pela API autenticada do painel.",
    "Redis descartável no CI; sem _FilaMemoria, Redis falso ou handle_envelope direto contornando a fila."
   ],
   "depende_de": [
    "T05"
   ],
   "dep_nota": "T06 (visitante) não é pré-requisito técnico, mas a primeira ação vertical é o visitante.",
   "proxima_acao": "Depois de T05 concluído: acrescentar Redis ao CI que executará a prova e escrever o percurso mínimo.",
   "responsavel": "Claude",
   "pr": [],
   "pr_referencia": null,
   "indicadores": {
    "implementacao": {
     "status": "nao_iniciado",
     "nota": ""
    },
    "validacao_local": {
     "status": "nao_iniciado",
     "nota": ""
    },
    "integracao_main": {
     "status": "pendente",
     "nota": ""
    },
    "publicacao_dev": {
     "status": "nao_aplicavel",
     "nota": "Prova de CI."
    },
    "publicacao_prod": {
     "status": "nao_aplicavel",
     "nota": "Prova de CI."
    },
    "ci": {
     "status": "nao_iniciado",
     "nota": "Sem PR de referência ainda."
    }
   },
   "evidencias": [],
   "prs": [],
   "dependencias_abertas": [
    "T05"
   ],
   "executavel": false,
   "situacao": "Futura",
   "estado_rotulo": "Futura"
  },
  {
   "id": "T08",
   "titulo": "Decidir região, teto de custo e executor do DEV online",
   "fase": "F3",
   "trilha": "principal",
   "sequencia": 8,
   "estado": "pronta",
   "objetivo": "Registrar a decisão do proprietário que libera o provisionamento do F3.",
   "criterio_aceite": [
    "Região, teto de custo e executor de deploy escolhidos e registrados no plano.",
    "Reuso do DEV histórico só depois de verificar identidade, ausência de dados reais e isolamento."
   ],
   "depende_de": [],
   "proxima_acao": "Proprietário decide região, teto e executor. Não bloqueia as entregas locais anteriores.",
   "responsavel": "proprietário",
   "pr": [],
   "pr_referencia": null,
   "indicadores": {
    "implementacao": {
     "status": "nao_aplicavel",
     "nota": "Decisão."
    },
    "validacao_local": {
     "status": "nao_aplicavel",
     "nota": "Decisão."
    },
    "integracao_main": {
     "status": "nao_aplicavel",
     "nota": "Decisão."
    },
    "publicacao_dev": {
     "status": "nao_aplicavel",
     "nota": "Decisão."
    },
    "publicacao_prod": {
     "status": "nao_aplicavel",
     "nota": "Decisão."
    },
    "ci": {
     "status": "nao_aplicavel",
     "nota": "Sem integração na main, sem CI."
    }
   },
   "evidencias": [],
   "prs": [],
   "dependencias_abertas": [],
   "executavel": true,
   "situacao": "Pronta",
   "estado_rotulo": "Pronta"
  },
  {
   "id": "T09",
   "titulo": "DEV online isolado com publicação automática",
   "fase": "F3",
   "trilha": "principal",
   "sequencia": 9,
   "estado": "futura",
   "objetivo": "Provisionar banco/Storage, Redis, autenticação e segredos próprios; publicar artefatos imutáveis do SHA integrado; serializar deploy, reset e reserva de aceite.",
   "criterio_aceite": [
    "Merge verde chega ao DEV identificado por SHA; navegador e simulador exercitam o fluxo com API, Redis e worker nos processos reais.",
    "Dois deploys concorrentes, reserva vigente ou expirada, reset e smoke falho não validam versão errada.",
    "Lembretes e avisos não são aceitos enquanto seus gates continuarem fechados; /health isolado não prova disponibilidade."
   ],
   "depende_de": [
    "T07",
    "T08"
   ],
   "proxima_acao": "Depois da prova F2b e da decisão T08: desenhar o fluxo de publicação (artefatos, migrations antes do código, seed DEV).",
   "responsavel": "Claude · proprietário (recursos)",
   "pr": [],
   "pr_referencia": null,
   "indicadores": {
    "implementacao": {
     "status": "nao_iniciado",
     "nota": ""
    },
    "validacao_local": {
     "status": "nao_iniciado",
     "nota": ""
    },
    "integracao_main": {
     "status": "pendente",
     "nota": ""
    },
    "publicacao_dev": {
     "status": "pendente",
     "nota": "O DEV online ainda não existe."
    },
    "publicacao_prod": {
     "status": "nao_aplicavel",
     "nota": "Etapa de DEV."
    },
    "ci": {
     "status": "nao_iniciado",
     "nota": "Sem PR de referência ainda."
    }
   },
   "evidencias": [],
   "prs": [],
   "dependencias_abertas": [
    "T07",
    "T08"
   ],
   "executavel": false,
   "situacao": "Futura",
   "estado_rotulo": "Futura"
  },
  {
   "id": "T10",
   "titulo": "Preparar promoção coordenada e recuperação",
   "fase": "F4",
   "trilha": "principal",
   "sequencia": 10,
   "estado": "futura",
   "objetivo": "Criar e ensaiar o caminho que recebe a revisão validada: compatibilidade de schema entre versões, contenção de consumidores, ensaio de atualização acumulada e backend/frontend compatíveis.",
   "criterio_aceite": [
    "Fixtures e ensaio cobrem migration aditiva, incompatibilidade, falha de migration, falha após a troca, frontend incompatível, fila pendente, interrupção e recuperação.",
    "Artefato final do frontend verificado contra o alvo correto, sem dados reais.",
    "Backend promovido por digest; rollback só quando o schema suporta a versão anterior."
   ],
   "depende_de": [
    "T09"
   ],
   "dep_nota": "Dependência derivada da sequência do plano: reaproveita artefatos imutáveis e o runner de migration empacotados no F3.",
   "proxima_acao": "Depois de T09: fechar as quatro lacunas do plano, uma por vez.",
   "responsavel": "Claude",
   "pr": [],
   "pr_referencia": null,
   "indicadores": {
    "implementacao": {
     "status": "nao_iniciado",
     "nota": ""
    },
    "validacao_local": {
     "status": "nao_iniciado",
     "nota": ""
    },
    "integracao_main": {
     "status": "pendente",
     "nota": ""
    },
    "publicacao_dev": {
     "status": "pendente",
     "nota": ""
    },
    "publicacao_prod": {
     "status": "nao_aplicavel",
     "nota": "Esta tarefa só prepara; não opera PROD."
    },
    "ci": {
     "status": "nao_iniciado",
     "nota": "Sem PR de referência ainda."
    }
   },
   "evidencias": [],
   "prs": [],
   "dependencias_abertas": [
    "T09"
   ],
   "executavel": false,
   "situacao": "Futura",
   "estado_rotulo": "Futura"
  },
  {
   "id": "T11",
   "titulo": "Operação de release em PROD (autorização explícita)",
   "fase": "F4",
   "trilha": "principal",
   "sequencia": 11,
   "estado": "futura",
   "objetivo": "Executar a transição já ensaiada para um SHA validado no DEV. Fica separada da preparação e não ativa novos envios, cobranças nem amplia o piloto.",
   "criterio_aceite": [
    "Preflight vivo, backup restaurável, migrations selecionadas, validação do schema, saúde e smoke.",
    "Autorização explícita do proprietário para este pacote concreto."
   ],
   "depende_de": [
    "T10"
   ],
   "proxima_acao": "Nenhuma antes de T10. A operação exige autorização nominal do proprietário.",
   "responsavel": "proprietário (autoriza) · Claude (executa se autorizado)",
   "pr": [],
   "pr_referencia": null,
   "indicadores": {
    "implementacao": {
     "status": "nao_iniciado",
     "nota": ""
    },
    "validacao_local": {
     "status": "nao_aplicavel",
     "nota": ""
    },
    "integracao_main": {
     "status": "nao_aplicavel",
     "nota": ""
    },
    "publicacao_dev": {
     "status": "nao_aplicavel",
     "nota": ""
    },
    "publicacao_prod": {
     "status": "pendente",
     "nota": "Sem evidência."
    },
    "ci": {
     "status": "nao_aplicavel",
     "nota": "Sem integração na main, sem CI."
    }
   },
   "evidencias": [],
   "prs": [],
   "dependencias_abertas": [
    "T10"
   ],
   "executavel": false,
   "situacao": "Futura",
   "estado_rotulo": "Futura"
  },
  {
   "id": "T12",
   "titulo": "Extrair a leitura da intenção de resposta do worker",
   "fase": "F5",
   "trilha": "principal",
   "sequencia": 12,
   "estado": "futura",
   "objetivo": "Mover _load_agent_reply_intent e a projeção _intent_from_message para um contrato pequeno fora do worker. Reserva, compare-and-set, entrega e callbacks ficam onde estão.",
   "criterio_aceite": [
    "Pelo menos um consumidor usa o contrato público de leitura.",
    "Existente/ausente, tenant A/B, chave histórica, estado nulo e fence produzem os mesmos resultados.",
    "Baseline dos cenários antes da extração e regressão depois, incluindo perda de lease e aceitação ambígua. Sem alteração de schema."
   ],
   "depende_de": [
    "T07"
   ],
   "dep_nota": "No plano, F4 vem antes da extração maior; F5 pode ser preparada depois da baseline F2b e não exige operar PROD.",
   "proxima_acao": "Depois de T07: levantar a baseline dos cenários de entrega que a extração pode afetar.",
   "responsavel": "Claude",
   "pr": [],
   "pr_referencia": null,
   "indicadores": {
    "implementacao": {
     "status": "nao_iniciado",
     "nota": ""
    },
    "validacao_local": {
     "status": "nao_iniciado",
     "nota": ""
    },
    "integracao_main": {
     "status": "pendente",
     "nota": ""
    },
    "publicacao_dev": {
     "status": "nao_aplicavel",
     "nota": ""
    },
    "publicacao_prod": {
     "status": "pendente",
     "nota": "Chega a PROD só em release."
    },
    "ci": {
     "status": "nao_iniciado",
     "nota": "Sem PR de referência ainda."
    }
   },
   "evidencias": [],
   "prs": [],
   "dependencias_abertas": [
    "T07"
   ],
   "executavel": false,
   "situacao": "Futura",
   "estado_rotulo": "Futura"
  },
  {
   "id": "S1",
   "titulo": "Triagem do monitor de produção (api-readiness)",
   "fase": "PAR",
   "trilha": "paralela",
   "estado": "em_andamento",
   "objetivo": "Determinar por que o Production monitor agendado falha, a partir dos registros do GitHub, sem sondagem nem intervenção em PROD.",
   "criterio_aceite": [
    "Causa registrada com evidência, ou lista do que falta para determiná-la.",
    "Nenhuma ação em PROD sem autorização própria; sem atribuir causa ou código HTTP não comprovados."
   ],
   "depende_de": [],
   "proxima_acao": "Proprietário informa o usuário SSH do host da API (ou executa os comandos de leitura com \"! ssh ...\"). Então: confirmar servidor, serviços e SHA implantado; ler readiness_probe_failed/error_type, erros SQL e heartbeat do cron-worker, sem alterar nada. Nenhuma correção em PROD sem aprovação prévia da causa e do impacto.",
   "responsavel": "proprietário (autorizar leitura em PROD)",
   "pr": [],
   "pr_referencia": null,
   "indicadores": {
    "implementacao": {
     "status": "nao_aplicavel",
     "nota": "Triagem somente leitura; sem código."
    },
    "validacao_local": {
     "status": "nao_aplicavel",
     "nota": "Triagem somente leitura; sem código."
    },
    "integracao_main": {
     "status": "nao_aplicavel",
     "nota": "Triagem."
    },
    "publicacao_dev": {
     "status": "nao_aplicavel",
     "nota": ""
    },
    "publicacao_prod": {
     "status": "desconhecido",
     "nota": "Estado vivo do backend de PROD ainda não lido (sem SSH). Supabase lido pelo conector, somente leitura."
    },
    "ci": {
     "status": "nao_aplicavel",
     "nota": "Sem integração na main, sem CI."
    }
   },
   "evidencias": [
    {
     "data": "2026-10-09",
     "tipo": "ci",
     "descricao": "As execuções agendadas do Production monitor falham continuamente desde 03/10 às 16:19 UTC (leitura do GitHub); o último schedule reprova o passo \"Fail workflow when production is unhealthy\" do job public-health. Causa não determinada.",
     "url": "https://github.com/haniellevi/PastorAI-LionClaw-V1/actions/workflows/production-monitor.yml"
    },
    {
     "data": "2026-10-09",
     "tipo": "ci",
     "descricao": "Execução 37936062411 (09/10 13:19 UTC, SHA d36ab813): api-liveness, app-public, admin-public e painel-public com 'HTTP 200 HTTPS'; apenas api-readiness falha com 'indisponivel (HTTPError)'. As duas execuções anteriores (37892253023, 37862292229) falham igualmente, segundo a listagem de execuções.",
     "url": "https://github.com/haniellevi/PastorAI-LionClaw-V1/actions/runs/37936062411"
    },
    {
     "data": "2026-10-09",
     "tipo": "revisao",
     "descricao": "deploy/monitoring/external_probe.py grava 'indisponivel (<tipo da exceção>)' para qualquer exceção do urllib; HTTPError é resposta não 2xx. backend/app/services/readiness.py devolve 503 quando status='not_ready' (banco/Redis obrigatórios), mas um 502/504 de proxy produziria o mesmo HTTPError. O código e o corpo não aparecem no log: causa não comprovada."
    },
    {
     "data": "2026-10-09",
     "tipo": "pr",
     "descricao": "Issue de incidente deduplicada #459 ('[Monitor] Produção PastorAI indisponível') aberta desde 03/10 16:19 UTC, atualizada pelo monitor, sem comentários.",
     "url": "https://github.com/haniellevi/PastorAI-LionClaw-V1/issues/459"
    },
    {
     "data": "2026-10-09",
     "tipo": "local",
     "descricao": "Consulta única, somente leitura e sem credenciais, autorizada pelo proprietário: GET https://api.igreja12.com.br/ready → HTTP 503, 3,96 s. Corpo: status=not_ready; required: database=unavailable, redis=ok; optional: evolution=ok, billing_operations=unknown; workers: queue-worker=ok, cron-worker=unavailable, broadcast-worker=ok. Isso explica o HTTPError do probe. Em backend/app/services/readiness.py, 'unavailable' cobre qualquer exceção na conexão ou consulta ao banco; a causa não aparece."
    },
    {
     "data": "2026-10-09",
     "tipo": "local",
     "descricao": "ACESSO OBTIDO — Supabase (conector autenticado, somente leitura): projeto pffafnchtxbimpwyaczq 'Pastor-Ai-LionClaw-v1', us-west-2, ACTIVE_HEALTHY. A identidade como PROD vem do PRODUCTION-RUNBOOK (registro), não de uma DATABASE_URL viva. ACESSO NÃO OBTIDO — SSH: falta o usuário; chaves e known_hosts existem, porta 22 responde."
    },
    {
     "data": "2026-10-09",
     "tipo": "local",
     "descricao": "DIAGNÓSTICO (logs Supavisor, janela de 24 h: 08/10 16:24Z a 09/10 16:16Z; o Supabase só retém essa janela): 1.085 falhas 'password authentication failed for user postgres' (modo session), ~45/h constantes, 0 sucessos desse cliente. Todas partem de um único IP, o mesmo para o qual api.igreja12.com.br resolve no DNS público; nenhuma parte do IP da VPS srv1728329. O pg_dump das 06:15Z autenticou com sucesso a partir de srv1728329 (backup noturno funcional). postgres_logs sem erro de consulta, permissão ou tabela; um FATAL isolado 'password authentication failed for user u' às 16:01Z (origem não analisada)."
    },
    {
     "data": "2026-10-09",
     "tipo": "revisao",
     "descricao": "HIPÓTESE, NÃO PROVADA: o host da API apresenta ao pooler uma credencial rejeitada (database=unavailable no /ready seria consequência). Não comprovado: que as falhas vêm do processo do backend (e não de outro cliente no mesmo IP), o error_type de readiness_probe_failed, o estado do heartbeat do cron-worker e a causa dos alertas desde 03/10 (fora da janela de logs). database=unavailable demonstra falha do probe, que também pode falhar depois da conexão."
    },
    {
     "data": "2026-10-09",
     "tipo": "revisao",
     "descricao": "Divergência documental: deploy/README.md indica a VPS srv1728329 (Campinas) como atual, mas api.igreja12.com.br resolve para outro IPv4. O servidor da API ainda não está identificado nominalmente; só srv1728329 foi vista no backup."
    }
   ],
   "aguardando": "Acesso SSH de leitura ao host que atende a API: falta o usuário SSH (há chaves locais e o host consta em known_hosts; nenhum alias ou usuário documentado). Sem isso não há como ler o erro do readiness, os logs do backend e o heartbeat do cron-worker.",
   "prs": [],
   "dependencias_abertas": [],
   "executavel": false,
   "situacao": "Em andamento",
   "estado_rotulo": "Em andamento"
  },
  {
   "id": "S2",
   "titulo": "Manutenção de worktrees (lotes nominais e recuperáveis)",
   "fase": "PAR",
   "trilha": "paralela",
   "estado": "futura",
   "objetivo": "Arquivar ou remover worktrees em lotes nominais, preservando branches, objetos, reflogs e volumes. Não é pré-requisito do desenvolvimento.",
   "criterio_aceite": [
    "Antes de cada lote: status, HEAD, reflogs, alcance de objetos, processos e ignorados verificados; restauração conferida.",
    "Nada de prune global; worktrees gerenciados pelo Codex são arquivados pela ferramenta proprietária."
   ],
   "depende_de": [],
   "proxima_acao": "Marcar pendência nos quatro candidatos com commits só em reflog antes de qualquer lote. Nenhuma limpeza nesta execução.",
   "responsavel": "proprietário (autoriza cada lote)",
   "pr": [],
   "pr_referencia": null,
   "indicadores": {
    "implementacao": {
     "status": "nao_iniciado",
     "nota": ""
    },
    "validacao_local": {
     "status": "nao_aplicavel",
     "nota": ""
    },
    "integracao_main": {
     "status": "nao_aplicavel",
     "nota": ""
    },
    "publicacao_dev": {
     "status": "nao_aplicavel",
     "nota": ""
    },
    "publicacao_prod": {
     "status": "nao_aplicavel",
     "nota": ""
    },
    "ci": {
     "status": "nao_aplicavel",
     "nota": "Sem integração na main, sem CI."
    }
   },
   "evidencias": [
    {
     "data": "2026-10-09",
     "tipo": "revisao",
     "descricao": "O inventário da revisão registra 153 secundários (90 registros sem pasta candidatos, oito pastas candidatas, 55 preservados), quatro vínculos inválidos e oito commits só em reflogs de quatro candidatos. Classificações condicionais de uma fotografia; não repetidas nesta execução."
    }
   ],
   "prs": [],
   "dependencias_abertas": [],
   "executavel": false,
   "situacao": "Futura",
   "estado_rotulo": "Futura"
  },
  {
   "id": "S3",
   "titulo": "Atualizar o Next.js (avisos moderados)",
   "fase": "PAR",
   "trilha": "paralela",
   "estado": "futura",
   "objetivo": "Corrigir os dois avisos moderados do Next 15.5.25, que ficam abaixo do limiar do audit, em patch próprio.",
   "criterio_aceite": [
    "Versão corretiva e compatibilidade verificadas no momento da execução; quatro checks aprovados.",
    "Sem misturar com outras atualizações."
   ],
   "depende_de": [
    "T01"
   ],
   "proxima_acao": "Depois de T01 integrado: conferir versão corretiva e abrir PR próprio.",
   "responsavel": "Claude",
   "pr": [],
   "pr_referencia": null,
   "indicadores": {
    "implementacao": {
     "status": "nao_iniciado",
     "nota": ""
    },
    "validacao_local": {
     "status": "nao_iniciado",
     "nota": ""
    },
    "integracao_main": {
     "status": "pendente",
     "nota": ""
    },
    "publicacao_dev": {
     "status": "nao_aplicavel",
     "nota": ""
    },
    "publicacao_prod": {
     "status": "pendente",
     "nota": "Chega a PROD pelo frontend."
    },
    "ci": {
     "status": "nao_iniciado",
     "nota": "Sem PR de referência ainda."
    }
   },
   "evidencias": [],
   "prs": [],
   "dependencias_abertas": [
    "T01"
   ],
   "executavel": false,
   "situacao": "Futura",
   "estado_rotulo": "Futura"
  },
  {
   "id": "S4",
   "titulo": "Triagem das vulnerabilidades altas do grafo completo (npm ci)",
   "fase": "PAR",
   "trilha": "paralela",
   "estado": "futura",
   "objetivo": "Diagnosticar individualmente as oito altas que o npm ci ainda relata no grafo completo, incluindo dependências de desenvolvimento, fora do recorte do audit com --omit=dev.",
   "criterio_aceite": [
    "Cada vulnerabilidade classificada (produção ou desenvolvimento, explorável ou não) com evidência.",
    "Não afirmar zero vulnerabilidades nem que só há avisos moderados."
   ],
   "depende_de": [
    "T01"
   ],
   "proxima_acao": "Depois de T01 integrado: rodar npm audit no grafo completo (somente leitura) e registrar o resultado.",
   "responsavel": "Claude",
   "pr": [],
   "pr_referencia": null,
   "indicadores": {
    "implementacao": {
     "status": "nao_aplicavel",
     "nota": "Triagem."
    },
    "validacao_local": {
     "status": "nao_iniciado",
     "nota": ""
    },
    "integracao_main": {
     "status": "nao_aplicavel",
     "nota": "Triagem."
    },
    "publicacao_dev": {
     "status": "nao_aplicavel",
     "nota": ""
    },
    "publicacao_prod": {
     "status": "nao_aplicavel",
     "nota": ""
    },
    "ci": {
     "status": "nao_aplicavel",
     "nota": "Sem integração na main, sem CI."
    }
   },
   "evidencias": [
    {
     "data": "2026-10-09",
     "tipo": "limite",
     "descricao": "Números vindos de logs de CI: npm ci do #463 relata 11 vulnerabilidades (3 moderadas, 8 altas); a base relatava 13 (3 moderadas, 10 altas). Sem diagnóstico individual."
    }
   ],
   "prs": [],
   "dependencias_abertas": [
    "T01"
   ],
   "executavel": false,
   "situacao": "Futura",
   "estado_rotulo": "Futura"
  },
  {
   "id": "B1",
   "titulo": "Centralizar leitura e diagnóstico de configuração",
   "fase": "BKL",
   "trilha": "backlog",
   "estado": "futura",
   "objetivo": "Começar por diagnóstico sanitizado e parser compartilhado, preservando a leitura tardia do Jev desligado e os gates independentes.",
   "criterio_aceite": [
    "Configuração opcional malformada não derruba rotas que não usam a integração.",
    "APP_ENV=development continua válido; qualquer novo valor com compatibilidade explícita."
   ],
   "depende_de": [],
   "proxima_acao": "Só abrir quando uma mudança real justificar. Condicionado a necessidade.",
   "responsavel": "—",
   "pr": [],
   "pr_referencia": null,
   "indicadores": {
    "implementacao": {
     "status": "nao_iniciado",
     "nota": ""
    },
    "validacao_local": {
     "status": "nao_iniciado",
     "nota": ""
    },
    "integracao_main": {
     "status": "pendente",
     "nota": ""
    },
    "publicacao_dev": {
     "status": "nao_aplicavel",
     "nota": ""
    },
    "publicacao_prod": {
     "status": "pendente",
     "nota": ""
    },
    "ci": {
     "status": "nao_iniciado",
     "nota": "Sem PR de referência ainda."
    }
   },
   "evidencias": [],
   "prs": [],
   "dependencias_abertas": [],
   "executavel": false,
   "situacao": "Futura",
   "estado_rotulo": "Futura"
  },
  {
   "id": "B2",
   "titulo": "Registro de ações do agente",
   "fase": "BKL",
   "trilha": "backlog",
   "estado": "futura",
   "objetivo": "Só avança quando uma capacidade concreta mostrar ganho. Separar a refatoração de qualquer funcionalidade nova, como pedido de oração.",
   "criterio_aceite": [
    "Confirmação transacional, privacidade, contratos de argumentos e CHECKs atuais preservados; mudança de schema em fatia própria."
   ],
   "depende_de": [],
   "proxima_acao": "Aguardar uma capacidade concreta. Condicionado a necessidade.",
   "responsavel": "—",
   "pr": [],
   "pr_referencia": null,
   "indicadores": {
    "implementacao": {
     "status": "nao_iniciado",
     "nota": ""
    },
    "validacao_local": {
     "status": "nao_iniciado",
     "nota": ""
    },
    "integracao_main": {
     "status": "pendente",
     "nota": ""
    },
    "publicacao_dev": {
     "status": "nao_aplicavel",
     "nota": ""
    },
    "publicacao_prod": {
     "status": "pendente",
     "nota": ""
    },
    "ci": {
     "status": "nao_iniciado",
     "nota": "Sem PR de referência ainda."
    }
   },
   "evidencias": [],
   "prs": [],
   "dependencias_abertas": [],
   "executavel": false,
   "situacao": "Futura",
   "estado_rotulo": "Futura"
  },
  {
   "id": "B3",
   "titulo": "Divergência de permissões no frontend (inbox customizado)",
   "fase": "BKL",
   "trilha": "backlog",
   "estado": "futura",
   "objetivo": "Definir e testar a visibilidade da inbox quando a matriz concede acesso customizado e a tela mantém lista fixa de papéis, sem ampliar acesso a dados.",
   "criterio_aceite": [
    "Teste de contrato nas permissões tocadas; sem endpoint /me alternativo.",
    "Política de acesso decidida pelo proprietário antes da mudança."
   ],
   "depende_de": [],
   "proxima_acao": "Decisão de produto do proprietário. Divergência é estática, sem reprodução em execução.",
   "responsavel": "proprietário (decisão)",
   "pr": [],
   "pr_referencia": null,
   "indicadores": {
    "implementacao": {
     "status": "nao_iniciado",
     "nota": ""
    },
    "validacao_local": {
     "status": "nao_iniciado",
     "nota": ""
    },
    "integracao_main": {
     "status": "pendente",
     "nota": ""
    },
    "publicacao_dev": {
     "status": "nao_aplicavel",
     "nota": ""
    },
    "publicacao_prod": {
     "status": "pendente",
     "nota": ""
    },
    "ci": {
     "status": "nao_iniciado",
     "nota": "Sem PR de referência ainda."
    }
   },
   "evidencias": [],
   "prs": [],
   "dependencias_abertas": [],
   "executavel": false,
   "situacao": "Futura",
   "estado_rotulo": "Futura"
  },
  {
   "id": "B4",
   "titulo": "Decisões de produto: opt-out no envio humano e reunião passada",
   "fase": "BKL",
   "trilha": "backlog",
   "estado": "futura",
   "objetivo": "Decidir se o envio humano deve checar opt-out e como tratar reunião passada na expectativa de visitante, sem mudar o comportamento por acidente em refatorações.",
   "criterio_aceite": [
    "Decisão registrada pelo proprietário antes de qualquer alteração de comportamento."
   ],
   "depende_de": [],
   "proxima_acao": "Aguardar decisão do proprietário.",
   "responsavel": "proprietário (decisão)",
   "pr": [],
   "pr_referencia": null,
   "indicadores": {
    "implementacao": {
     "status": "nao_aplicavel",
     "nota": "Decisão."
    },
    "validacao_local": {
     "status": "nao_aplicavel",
     "nota": "Decisão."
    },
    "integracao_main": {
     "status": "nao_aplicavel",
     "nota": "Decisão."
    },
    "publicacao_dev": {
     "status": "nao_aplicavel",
     "nota": ""
    },
    "publicacao_prod": {
     "status": "nao_aplicavel",
     "nota": ""
    },
    "ci": {
     "status": "nao_aplicavel",
     "nota": "Sem integração na main, sem CI."
    }
   },
   "evidencias": [],
   "prs": [],
   "dependencias_abertas": [],
   "executavel": false,
   "situacao": "Futura",
   "estado_rotulo": "Futura"
  },
  {
   "id": "B5",
   "titulo": "Avaliar código e testes candidatos à retirada, um a um",
   "fase": "BKL",
   "trilha": "backlog",
   "estado": "futura",
   "objetivo": "Examinar consumidor e finalidade de cada candidato (scripts, módulos de evidência, testes estruturais) antes de remover. Preservar frentes pausadas.",
   "criterio_aceite": [
    "Remoção só com consumidor e finalidade examinados e equivalente comportamental do teste identificado.",
    "Falta de referência textual, flag desligada ou uso de hash não bastam."
   ],
   "depende_de": [],
   "proxima_acao": "Aguardar necessidade real. Condicionado.",
   "responsavel": "—",
   "pr": [],
   "pr_referencia": null,
   "indicadores": {
    "implementacao": {
     "status": "nao_iniciado",
     "nota": ""
    },
    "validacao_local": {
     "status": "nao_iniciado",
     "nota": ""
    },
    "integracao_main": {
     "status": "pendente",
     "nota": ""
    },
    "publicacao_dev": {
     "status": "nao_aplicavel",
     "nota": ""
    },
    "publicacao_prod": {
     "status": "pendente",
     "nota": ""
    },
    "ci": {
     "status": "nao_iniciado",
     "nota": "Sem PR de referência ainda."
    }
   },
   "evidencias": [],
   "prs": [],
   "dependencias_abertas": [],
   "executavel": false,
   "situacao": "Futura",
   "estado_rotulo": "Futura"
  },
  {
   "id": "B6",
   "titulo": "Baseline de métricas por fatia",
   "fase": "BKL",
   "trilha": "backlog",
   "estado": "futura",
   "objetivo": "Registrar uma linha por fatia: tempo até o primeiro teste útil, duração e espera do CI, ações manuais até DEV/PROD e dispersão entre módulos. Nenhum ganho está comprovado.",
   "criterio_aceite": [
    "Medições reais, com origem, sem converter linhas, camadas ou contagem de commits em prazo."
   ],
   "depende_de": [],
   "proxima_acao": "Coletar a primeira linha na próxima fatia concluída.",
   "responsavel": "Claude",
   "pr": [],
   "pr_referencia": null,
   "indicadores": {
    "implementacao": {
     "status": "nao_iniciado",
     "nota": ""
    },
    "validacao_local": {
     "status": "nao_aplicavel",
     "nota": ""
    },
    "integracao_main": {
     "status": "nao_aplicavel",
     "nota": ""
    },
    "publicacao_dev": {
     "status": "nao_aplicavel",
     "nota": ""
    },
    "publicacao_prod": {
     "status": "nao_aplicavel",
     "nota": ""
    },
    "ci": {
     "status": "nao_aplicavel",
     "nota": "Sem integração na main, sem CI."
    }
   },
   "evidencias": [],
   "prs": [],
   "dependencias_abertas": [],
   "executavel": false,
   "situacao": "Futura",
   "estado_rotulo": "Futura"
  }
 ],
 "historico": [
  {
   "data": "2026-10-09",
   "titulo": "PR #461 aberto: regras únicas em AGENTS.md e DEV online (Passo 0)",
   "descricao": "Consolidou as regras de trabalho em AGENTS.md, restringiu a revisão independente e registrou a decisão do DEV online. Aberto, não integrado.",
   "tarefa": "T02",
   "pr": 461,
   "sha": "bed02fabfb43588e2fa7963727f5d4b9ee96a28c"
  },
  {
   "data": "2026-10-09",
   "titulo": "PR #462 aberto: simulador de WhatsApp (candidato F2a)",
   "descricao": "Evolution falsa, página de chat e modo WHATSAPP_TRANSPORTE=simulado. Aberto, com defeitos conhecidos a corrigir; não integrado.",
   "tarefa": "T05",
   "pr": 462,
   "sha": "08e8928216da35040b3d3cc5f08edb9ca62d3b8b"
  },
  {
   "data": "2026-10-09",
   "titulo": "PR #463 aberto: dependências reprovadas pelos audits",
   "descricao": "LangGraph 1.2.14, sharp 0.35.5 e source-map-js 1.2.2. Checks de produto aprovados no CI e validação local registrada. Aberto, aguardando integração.",
   "tarefa": "T01",
   "pr": 463,
   "sha": "9f61ba5e087b60d4336d21ed2d025996dff2cdc3"
  },
  {
   "data": "2026-10-09",
   "titulo": "Plano consolidado e painel de acompanhamento no #461",
   "descricao": "O plano versionado foi substituído pelo consolidado, com links portáveis e apêndice de propostas retiradas. Painel, dados e comando de atualização criados. Aguarda revisão e CI.",
   "tarefa": "T02",
   "pr": 461
  },
  {
   "data": "2026-10-09",
   "titulo": "PR #464 aberto: test-local.sh rejeita alvo desconhecido",
   "descricao": "Alvo fora de todos/backend/frontend sai com 2 antes de executar qualquer ferramenta; teste e sprint incluídos. Aberto, aguardando CI e integração.",
   "tarefa": "T04",
   "pr": 464,
   "sha": "18cef626"
  },
  {
   "data": "2026-10-09",
   "titulo": "S1: acesso Supabase obtido, SSH pendente; causa ainda não provada",
   "descricao": "1.085 falhas de autenticação no pooler vindas do IP da API; backup de srv1728329 autentica. Hipótese de credencial rejeitada no host da API, sem prova. Falta o usuário SSH.",
   "tarefa": "S1"
  },
  {
   "data": "2026-10-09",
   "titulo": "T05 iniciada; dependências T05/T06 reclassificadas",
   "descricao": "T05 passa a depender só de si; integra após T01. T06 depende de T05 por ordem do plano.",
   "tarefa": "T05"
  },
  {
   "data": "2026-10-09",
   "titulo": "T05 fatia 1: validador de destino do simulador (local)",
   "descricao": "Commit local 0ffcb754 com 57 testes verdes; não enviado ao #462.",
   "tarefa": "T05",
   "pr": 462,
   "sha": "0ffcb754"
  }
 ],
 "github": {
  "repositorio": "haniellevi/PastorAI-LionClaw-V1",
  "tentativa_em": "2026-10-09T13:26:52-03:00",
  "prs": {
   "461": {
    "ok": true,
    "consultado_em": "2026-10-09T13:26:52-03:00",
    "tentativa_em": "2026-10-09T13:26:52-03:00",
    "erro": null,
    "dados": {
     "numero": 461,
     "titulo": "docs: consolidar regras em AGENTS.md e adotar DEV online (Passo 0)",
     "url": "https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/461",
     "estado": "OPEN",
     "rascunho": false,
     "criado_em": "2026-10-09T12:41:49Z",
     "atualizado_em": "2026-10-09T16:05:03Z",
     "integrado_em": null,
     "branch": "docs/passo0-regras-dev-online",
     "base": "main",
     "sha": "a242b751379a93b37f04933b077e7016c54b0494",
     "sha_base": "d36ab813bf45f8bc92fd605425394570e85ad3ec",
     "mergeavel": "MERGEABLE",
     "revisao": "",
     "checks": [
      {
       "nome": "backend-tests",
       "status": "COMPLETED",
       "conclusao": "FAILURE",
       "url": "https://github.com/haniellevi/PastorAI-LionClaw-V1/actions/runs/37956428263/job/113908001428"
      },
      {
       "nome": "frontend-ci",
       "status": "COMPLETED",
       "conclusao": "FAILURE",
       "url": "https://github.com/haniellevi/PastorAI-LionClaw-V1/actions/runs/37956428391/job/113908001855"
      },
      {
       "nome": "e2e-critical",
       "status": "COMPLETED",
       "conclusao": "SUCCESS",
       "url": "https://github.com/haniellevi/PastorAI-LionClaw-V1/actions/runs/37956428341/job/113908001733"
      },
      {
       "nome": "rls-integration",
       "status": "COMPLETED",
       "conclusao": "SUCCESS",
       "url": "https://github.com/haniellevi/PastorAI-LionClaw-V1/actions/runs/37956428306/job/113908002018"
      },
      {
       "nome": "tooling-static",
       "status": "COMPLETED",
       "conclusao": "SUCCESS",
       "url": "https://github.com/haniellevi/PastorAI-LionClaw-V1/actions/runs/37956428272/job/113908001869"
      },
      {
       "nome": "Vercel",
       "status": "SUCCESS",
       "conclusao": null,
       "url": "https://vercel.com/raniel-levis-projects/pastorai-frontend-prod/FkryHQawtFqGHRTX2FQa7ecQPejp"
      },
      {
       "nome": "Vercel Preview Comments",
       "status": "COMPLETED",
       "conclusao": "SUCCESS",
       "url": "https://vercel.com/github"
      }
     ]
    }
   },
   "462": {
    "ok": true,
    "consultado_em": "2026-10-09T13:26:53-03:00",
    "tentativa_em": "2026-10-09T13:26:53-03:00",
    "erro": null,
    "dados": {
     "numero": 462,
     "titulo": "feat: simulador de WhatsApp com transporte simulado (Fatia 1)",
     "url": "https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/462",
     "estado": "OPEN",
     "rascunho": false,
     "criado_em": "2026-10-09T13:24:54Z",
     "atualizado_em": "2026-10-09T13:25:39Z",
     "integrado_em": null,
     "branch": "feat/simulador-whatsapp",
     "base": "main",
     "sha": "08e8928216da35040b3d3cc5f08edb9ca62d3b8b",
     "sha_base": "d36ab813bf45f8bc92fd605425394570e85ad3ec",
     "mergeavel": "MERGEABLE",
     "revisao": "",
     "checks": [
      {
       "nome": "backend-tests",
       "status": "COMPLETED",
       "conclusao": "FAILURE",
       "url": "https://github.com/haniellevi/PastorAI-LionClaw-V1/actions/runs/37936670182/job/113840332981"
      },
      {
       "nome": "frontend-ci",
       "status": "COMPLETED",
       "conclusao": "FAILURE",
       "url": "https://github.com/haniellevi/PastorAI-LionClaw-V1/actions/runs/37936670249/job/113840332008"
      },
      {
       "nome": "e2e-critical",
       "status": "COMPLETED",
       "conclusao": "SUCCESS",
       "url": "https://github.com/haniellevi/PastorAI-LionClaw-V1/actions/runs/37936670153/job/113840332009"
      },
      {
       "nome": "rls-integration",
       "status": "COMPLETED",
       "conclusao": "SUCCESS",
       "url": "https://github.com/haniellevi/PastorAI-LionClaw-V1/actions/runs/37936670113/job/113840331677"
      },
      {
       "nome": "tooling-static",
       "status": "COMPLETED",
       "conclusao": "SUCCESS",
       "url": "https://github.com/haniellevi/PastorAI-LionClaw-V1/actions/runs/37936670338/job/113840332669"
      },
      {
       "nome": "Vercel",
       "status": "SUCCESS",
       "conclusao": null,
       "url": "https://vercel.com/raniel-levis-projects/pastorai-frontend-prod/3swkFeQvMDbj1yZPkjBUcDECe7VG"
      },
      {
       "nome": "Vercel Preview Comments",
       "status": "COMPLETED",
       "conclusao": "SUCCESS",
       "url": "https://vercel.com/github"
      }
     ]
    }
   },
   "463": {
    "ok": true,
    "consultado_em": "2026-10-09T13:26:54-03:00",
    "tentativa_em": "2026-10-09T13:26:54-03:00",
    "erro": null,
    "dados": {
     "numero": 463,
     "titulo": "fix: atualizar dependências reprovadas pelos audits",
     "url": "https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/463",
     "estado": "OPEN",
     "rascunho": false,
     "criado_em": "2026-10-09T14:32:46Z",
     "atualizado_em": "2026-10-09T14:33:30Z",
     "integrado_em": null,
     "branch": "fix/deps-audit-20261009",
     "base": "main",
     "sha": "9f61ba5e087b60d4336d21ed2d025996dff2cdc3",
     "sha_base": "d36ab813bf45f8bc92fd605425394570e85ad3ec",
     "mergeavel": "MERGEABLE",
     "revisao": "",
     "checks": [
      {
       "nome": "backend-tests",
       "status": "COMPLETED",
       "conclusao": "SUCCESS",
       "url": "https://github.com/haniellevi/PastorAI-LionClaw-V1/actions/runs/37944984761/job/113868823091"
      },
      {
       "nome": "e2e-critical",
       "status": "COMPLETED",
       "conclusao": "SUCCESS",
       "url": "https://github.com/haniellevi/PastorAI-LionClaw-V1/actions/runs/37944984708/job/113868824514"
      },
      {
       "nome": "frontend-ci",
       "status": "COMPLETED",
       "conclusao": "SUCCESS",
       "url": "https://github.com/haniellevi/PastorAI-LionClaw-V1/actions/runs/37944984799/job/113868824569"
      },
      {
       "nome": "rls-integration",
       "status": "COMPLETED",
       "conclusao": "SUCCESS",
       "url": "https://github.com/haniellevi/PastorAI-LionClaw-V1/actions/runs/37944984710/job/113868822541"
      },
      {
       "nome": "tooling-static",
       "status": "COMPLETED",
       "conclusao": "SUCCESS",
       "url": "https://github.com/haniellevi/PastorAI-LionClaw-V1/actions/runs/37944984775/job/113868823007"
      },
      {
       "nome": "Vercel",
       "status": "SUCCESS",
       "conclusao": null,
       "url": "https://vercel.com/raniel-levis-projects/pastorai-frontend-prod/hQFPqJ62qCnqHzWEqn1L3wBZLQtA"
      },
      {
       "nome": "Vercel Preview Comments",
       "status": "COMPLETED",
       "conclusao": "SUCCESS",
       "url": "https://vercel.com/github"
      }
     ]
    }
   },
   "464": {
    "ok": true,
    "consultado_em": "2026-10-09T13:26:55-03:00",
    "tentativa_em": "2026-10-09T13:26:55-03:00",
    "erro": null,
    "dados": {
     "numero": 464,
     "titulo": "fix: test-local.sh rejeita alvo desconhecido",
     "url": "https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/464",
     "estado": "OPEN",
     "rascunho": false,
     "criado_em": "2026-10-09T16:07:47Z",
     "atualizado_em": "2026-10-09T16:08:29Z",
     "integrado_em": null,
     "branch": "fix/test-local-alvo-desconhecido",
     "base": "main",
     "sha": "18cef6267801955da657403b4f96780f3a22aa8d",
     "sha_base": "d36ab813bf45f8bc92fd605425394570e85ad3ec",
     "mergeavel": "MERGEABLE",
     "revisao": "",
     "checks": [
      {
       "nome": "backend-tests",
       "status": "COMPLETED",
       "conclusao": "FAILURE",
       "url": "https://github.com/haniellevi/PastorAI-LionClaw-V1/actions/runs/37956848484/job/113909423818"
      },
      {
       "nome": "frontend-ci",
       "status": "COMPLETED",
       "conclusao": "FAILURE",
       "url": "https://github.com/haniellevi/PastorAI-LionClaw-V1/actions/runs/37956848356/job/113909423903"
      },
      {
       "nome": "e2e-critical",
       "status": "COMPLETED",
       "conclusao": "SUCCESS",
       "url": "https://github.com/haniellevi/PastorAI-LionClaw-V1/actions/runs/37956848321/job/113909422283"
      },
      {
       "nome": "rls-integration",
       "status": "COMPLETED",
       "conclusao": "SUCCESS",
       "url": "https://github.com/haniellevi/PastorAI-LionClaw-V1/actions/runs/37956848343/job/113909422716"
      },
      {
       "nome": "tooling-static",
       "status": "COMPLETED",
       "conclusao": "SUCCESS",
       "url": "https://github.com/haniellevi/PastorAI-LionClaw-V1/actions/runs/37956848332/job/113909422696"
      },
      {
       "nome": "Vercel",
       "status": "SUCCESS",
       "conclusao": null,
       "url": "https://vercel.com/raniel-levis-projects/pastorai-frontend-prod/BJuZiP1DKFnXyWZcPQU4gNgbxhNH"
      },
      {
       "nome": "Vercel Preview Comments",
       "status": "COMPLETED",
       "conclusao": "SUCCESS",
       "url": "https://vercel.com/github"
      }
     ]
    }
   }
  },
  "main": {
   "ok": true,
   "consultado_em": "2026-10-09T13:26:55-03:00",
   "tentativa_em": "2026-10-09T13:26:55-03:00",
   "erro": null,
   "dados": {
    "data": "2026-10-02T19:24:12Z",
    "mensagem": "Merge pull request #458 from haniellevi/feat/mvp-own-visitor-release-20261002",
    "sha": "d36ab813bf45f8bc92fd605425394570e85ad3ec",
    "url": "https://github.com/haniellevi/PastorAI-LionClaw-V1/commit/d36ab813bf45f8bc92fd605425394570e85ad3ec"
   }
  },
  "monitores": {
   "production-monitor": {
    "ok": true,
    "consultado_em": "2026-10-09T13:26:56-03:00",
    "tentativa_em": "2026-10-09T13:26:56-03:00",
    "erro": null,
    "dados": {
     "workflow": "production-monitor.yml",
     "descricao": "Production monitor (agendado)",
     "consultadas": 40,
     "falhas_consecutivas": 27,
     "falhas_desde": "2026-10-03T16:19:12Z",
     "todas_falharam": false,
     "ultimas": [
      {
       "id": 37936062411,
       "conclusao": "failure",
       "status": "completed",
       "criado_em": "2026-10-09T13:19:49Z",
       "sha": "d36ab813bf45f8bc92fd605425394570e85ad3ec",
       "evento": "schedule",
       "url": "https://github.com/haniellevi/PastorAI-LionClaw-V1/actions/runs/37936062411"
      },
      {
       "id": 37892253023,
       "conclusao": "failure",
       "status": "completed",
       "criado_em": "2026-10-09T06:11:27Z",
       "sha": "d36ab813bf45f8bc92fd605425394570e85ad3ec",
       "evento": "schedule",
       "url": "https://github.com/haniellevi/PastorAI-LionClaw-V1/actions/runs/37892253023"
      },
      {
       "id": 37862292229,
       "conclusao": "failure",
       "status": "completed",
       "criado_em": "2026-10-08T23:57:53Z",
       "sha": "d36ab813bf45f8bc92fd605425394570e85ad3ec",
       "evento": "schedule",
       "url": "https://github.com/haniellevi/PastorAI-LionClaw-V1/actions/runs/37862292229"
      },
      {
       "id": 37832223006,
       "conclusao": "failure",
       "status": "completed",
       "criado_em": "2026-10-08T19:28:33Z",
       "sha": "d36ab813bf45f8bc92fd605425394570e85ad3ec",
       "evento": "schedule",
       "url": "https://github.com/haniellevi/PastorAI-LionClaw-V1/actions/runs/37832223006"
      },
      {
       "id": 37785171907,
       "conclusao": "failure",
       "status": "completed",
       "criado_em": "2026-10-08T13:32:37Z",
       "sha": "d36ab813bf45f8bc92fd605425394570e85ad3ec",
       "evento": "schedule",
       "url": "https://github.com/haniellevi/PastorAI-LionClaw-V1/actions/runs/37785171907"
      }
     ]
    }
   }
  }
 },
 "resumo": {
  "etapa_atual": {
   "fase": "PREP",
   "nome": "Preparação: dependências",
   "tarefa": "T01",
   "situacao": "Validado — aguardando integração"
  },
  "proxima_executavel": "T08",
  "tambem_prontas": [],
  "em_curso": [
   "T01",
   "T02",
   "T04",
   "T05",
   "S1"
  ],
  "bloqueios": [
   {
    "id": "T03",
    "titulo": "Atualizar a base do #461 e revalidar",
    "motivo": "O #463 ainda não foi integrado (aguarda autorização do proprietário)."
   }
  ],
  "esperas": [
   {
    "id": "T01",
    "titulo": "Corrigir as dependências herdadas da main (PR #463)",
    "motivo": "Integração na main: depende da autorização do proprietário. Esta execução não faz merge."
   },
   {
    "id": "T02",
    "titulo": "Plano consolidado e painel de acompanhamento (PR #461)",
    "motivo": "CI do PR: backend-tests e frontend-ci reprovam por audits herdados da main até a base ser atualizada (T03)."
   },
   {
    "id": "T04",
    "titulo": "test-local.sh rejeita alvo desconhecido",
    "motivo": "Integração do #463 (corrige os audits), depois rebase/revalidação do #464 e autorização do proprietário. Esta execução não faz merge."
   },
   {
    "id": "S1",
    "titulo": "Triagem do monitor de produção (api-readiness)",
    "motivo": "Acesso SSH de leitura ao host que atende a API: falta o usuário SSH (há chaves locais e o host consta em known_hosts; nenhum alias ou usuário documentado). Sem isso não há como ler o erro do readiness, os logs do backend e o heartbeat do cron-worker."
   }
  ],
  "contagem": {
   "futura": 15,
   "pronta": 1,
   "em_andamento": 2,
   "em_validacao": 3,
   "bloqueada": 1,
   "concluida": 0
  },
  "proporcao": {
   "geral": {
    "concluidas": 0,
    "total": 22,
    "texto": "0 de 22 tarefas concluídas"
   },
   "principal": {
    "concluidas": 0,
    "total": 12,
    "texto": "0 de 12 tarefas concluídas"
   },
   "paralela": {
    "concluidas": 0,
    "total": 4,
    "texto": "0 de 4 tarefas concluídas"
   },
   "backlog": {
    "concluidas": 0,
    "total": 6,
    "texto": "0 de 6 tarefas concluídas"
   },
   "formula": "tarefas em estado Concluída ÷ tarefas cadastradas. É contagem de itens, não medida de esforço nem de prazo."
  }
 }
};
