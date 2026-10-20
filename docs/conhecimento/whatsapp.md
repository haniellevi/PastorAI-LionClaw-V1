# Conhecimento oficial no WhatsApp — desligado

`CONHECIMENTO_WHATSAPP_APPROVED_RELEASE_ID=None` e
`CONHECIMENTO_WHATSAPP_ENABLED_IGREJA_IDS` vazia por padrão. Release e lista
cumulativas; retorno antes de sessão ou provedor quando desligado. Nenhuma
configuração operacional, exemplo de ambiente ou workflow foi alterado.

Comando fechado: `CONHECIMENTO buscar TERMO`, até 200 caracteres, no máximo três
citações de 300 caracteres. `CONHECIMENTO` explica o uso. Catálogo tipado não
aceita tenant, usuário, papel, público nem IDs fornecidos pelo modelo. A identidade
vem do contato/conversa/inbound persistidos; usuário ativo único é revalidado.
Sem usuário vinculado, o contato é visitante e só lê institucional público.
Acesso revogado ou ambíguo não cai para visitante. A mesma busca do painel
revalida vínculo/papéis/públicos e exige versão publicada vigente.

Trechos são dados citados literalmente, nunca prompt/instrução; nenhum LLM
sintetiza fatos ou executa texto recuperado. A fonte contém título, ID imutável
da versão e seção. A resposta é persistida antes do transporte existente.
Toda entrega/retry refaz a busca pelo inbound e compara resposta/identidade:
revogação/substituição/perda de público suprime resposta pendente. Conversas
não criam documentos nem alimentam a busca. Não há novos vetores ou migrations.

Opt-out, crise e pedido de humano prevalecem; consentimento, handoff existente,
conexão, piloto, credencial e gates de envio continuam no caminho comum.
Sem fonte autorizada, declara lacuna sem revelar se existem fontes restritas e,
após entregar o aviso, marca a conversa para humano pelo serviço existente.
A decisão 21 permanece provisória: encaminhamento vai ao inbox humano comum;
não há distribuição automática a um responsável de setor ainda não configurado.

Sarah deve revisar autorização do agente e compatibilidade com RLS/migrations
existentes e com a exclusão da fatia 5 antes da integração/qualquer ativação.
Produção, banco remoto, deploy e aceite pastoral não verificados. Esta fatia não
autoriza ativação ou ampliação do piloto. Testes usam provedores simulados e
substituem gates somente nas fixtures sintéticas.
