# Conhecimento oficial no WhatsApp — desligado

`CONHECIMENTO_WHATSAPP_APPROVED_RELEASE_ID=None` e
`CONHECIMENTO_WHATSAPP_ENABLED_IGREJA_IDS` vazia por padrão. Release e lista
cumulativas; retorno antes de sessão ou provedor quando desligado. Nenhuma
configuração operacional, exemplo de ambiente ou workflow foi alterado.

Comando fechado: `CONHECIMENTO buscar TERMO`, até 200 caracteres, no máximo três
citações de 300 caracteres. `CONHECIMENTO` e `CONHECIMENTO buscar` sem termo explicam o uso. Outras frases seguem o fluxo normal, inclusive durante coleta de oração. Catálogo tipado não
aceita tenant, usuário, papel, público nem IDs fornecidos pelo modelo. A identidade
vem do contato/conversa/inbound persistidos; usuário ativo único é revalidado.
Sem usuário vinculado, o contato é visitante e só lê institucional público.
Acesso revogado ou ambíguo não cai para visitante. A mesma busca do painel
revalida vínculo/papéis/públicos e exige versão publicada vigente.

Trechos são dados citados com espaços normalizados e `Fonte:` neutralizada, nunca prompt/instrução; nenhum LLM
sintetiza fatos ou executa texto recuperado. A fonte contém título, número legível
da versão (ordem por criação/ID somente entre snapshots legíveis pelo leitor) e seção. A resposta é persistida antes do transporte existente.
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


Contrato de exclusão com a #524: toda resposta deste fluxo persiste
`messages.agent_privilege_context.kind="conhecimento"`. Respostas com citações
(`stage="result"`) incluem `fontes`, uma lista de objetos contendo somente
`documento_id` e `versao_id` internos (UUIDs como strings), um por citação.
Não há texto, título, trecho ou consulta nesse marcador adicional; os IDs não
são exibidos ao destinatário. O marcador é commitado com `messages.texto` antes
do transporte e comparado novamente na autorização de entrega/retry.
Ajuda, recusa e lacuna mantêm `kind`, sem `fontes`, pois não contêm excertos.
A #524 deve usar igreja + documento/versão desse contrato para localizar e
redigir/apagar excertos em `messages.texto`, inclusive já entregues. Esta PR
apenas marca as respostas: não implementa essa limpeza. A exclusão atual de
documentos ainda não alcança esses excertos; a integração dessa limpeza é
pendência antes de qualquer ativação.
