# Usuários de Smoke DEV

O arquivo local `usuario-dev.md`, na raiz do projeto, é a fonte de credenciais para os smokes autenticados do ambiente DEV.

## Regra de uso

- Leia `<raiz-do-checkout-principal>/usuario-dev.md` antes de iniciar um smoke autenticado. O caminho é local de cada máquina e não deve ser fixado neste documento.
- Escolha a conta pelo papel que o cenário exige: administração, pastor, liderança de célula, membro ou console da plataforma.
- Use essas contas somente no DEV (`Igreja12-dev` / Supabase `cxmjojnocigekgcxhubi`).
- Nunca coloque a senha em arquivos versionados, no protótipo, em screenshots, logs ou mensagens de handoff.
- `usuario-dev.md` é ignorado pelo Git. Worktrees novos não o recebem automaticamente; confirme a presença local antes do teste.

## Registro do smoke

Ao concluir, registre apenas: ambiente, papel usado, tela/fluxo, resultado e eventual divergência. Não registre a senha.
