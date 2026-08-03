import type { Metadata } from "next";

import { LegalDocument } from "@/components/legal/LegalDocument";
import { LEGAL_CONTACT_EMAIL, LEGAL_NAME } from "@/components/legal/legal-config";

export const metadata: Metadata = {
  title: "Política de Privacidade",
  description:
    "Como o Igreja 12 coleta, utiliza, protege e compartilha dados pessoais no painel, WhatsApp, IA e Google Calendar.",
};

export default function PrivacyPage() {
  return (
    <LegalDocument
      title="Política de Privacidade"
      description="Esta política explica, em linguagem direta, quais dados o Igreja 12 trata, para quais finalidades e como cada pessoa pode exercer seus direitos."
    >
      <h2 id="escopo">1. A quem esta política se aplica</h2>
      <p>
        Esta Política de Privacidade se aplica ao painel e aos serviços do {LEGAL_NAME},
        incluindo as experiências em <strong>app.igreja12.com.br</strong>, as integrações
        com o número oficial de WhatsApp da igreja, Google Calendar, serviços de
        inteligência artificial, cobrança e comunicações transacionais.
      </p>
      <p>Ela abrange três grupos principais:</p>
      <ul>
        <li>administradores, pastores, líderes e demais usuários com conta no painel;</li>
        <li>
          membros, visitantes e contatos cujos dados são cadastrados pela igreja ou
          enviados por eles ao número oficial de WhatsApp;
        </li>
        <li>
          representantes da igreja responsáveis pela contratação, configuração e
          pagamento do serviço.
        </li>
      </ul>

      <h2 id="papeis">2. Quem decide sobre o uso dos dados</h2>
      <p>
        Para os dados pastorais de membros, visitantes e contatos, a igreja que utiliza
        o sistema normalmente define por que e como os dados serão usados. Nesse contexto,
        a <strong>igreja contratante atua como controladora</strong> e o {LEGAL_NAME} atua
        como <strong>operador da plataforma</strong>, seguindo as instruções legítimas da
        igreja e os limites desta política.
      </p>
      <p>
        Para dados necessários à criação de contas, segurança do serviço, prevenção a
        fraude, cobrança, suporte e cumprimento de obrigações próprias, o {LEGAL_NAME}
        pode atuar como controlador. Em todos os casos, cada igreja continua responsável
        por conceder acesso apenas a pessoas autorizadas e por definir uma base legal
        adequada para seus registros pastorais.
      </p>

      <h2 id="dados">3. Quais dados tratamos</h2>

      <h3>3.1. Contas e usuários do painel</h3>
      <ul>
        <li>nome, e-mail, telefone e igreja vinculada;</li>
        <li>perfil, função ministerial, permissões e histórico de acesso;</li>
        <li>identificadores de autenticação e informações de segurança da sessão;</li>
        <li>convites, redefinições de senha e registros de auditoria.</li>
      </ul>

      <h3>3.2. Pessoas acompanhadas pela igreja</h3>
      <p>
        Conforme o uso feito pela igreja, o sistema pode armazenar nome, telefone,
        e-mail, data de nascimento ou faixa etária, endereço, célula, liderança,
        presença em reuniões, visitas, etapas de consolidação e discipulado, pedidos de
        acompanhamento, consentimentos e preferências de comunicação.
      </p>
      <p>
        Alguns desses registros podem revelar <strong>convicção religiosa</strong>,
        participação em igreja, necessidades pastorais ou pedidos de oração. A LGPD
        classifica informações religiosas como dados pessoais sensíveis. Por isso, seu
        acesso deve ser restrito ao necessário, com cuidado reforçado e uma base legal
        definida pela igreja responsável.
      </p>

      <h3>3.3. WhatsApp oficial</h3>
      <p>
        Quando uma pessoa conversa com o número oficial conectado pela igreja, podemos
        tratar número de telefone, nome de perfil, conteúdo das mensagens, data e hora,
        estado do atendimento e arquivos enviados, como imagens e áudios. Conversas em
        números pessoais de pastores ou líderes não fazem parte do serviço e não devem
        ser capturadas pelo sistema.
      </p>

      <h3>3.4. Google Calendar</h3>
      <p>
        Quando um administrador conecta uma conta Google, tratamos o e-mail verificado da
        conta, um identificador estável fornecido pelo Google, tokens de autorização
        protegidos, a agenda escolhida e os dados mínimos dos eventos necessários para a
        sincronização. <strong>O {LEGAL_NAME} nunca recebe a senha da conta Google.</strong>
      </p>
      <p>
        O uso de informações recebidas das APIs do Google Workspace observa a
        <a
          href="https://developers.google.com/terms/api-services-user-data-policy"
          rel="noreferrer"
          target="_blank"
        >
          {" "}Política de Dados do Usuário dos Serviços de API do Google
        </a>
        , incluindo os requisitos de <strong>Uso Limitado (Limited Use)</strong>.
        Dados do Google são utilizados somente para oferecer e manter a sincronização
        solicitada pela igreja. Eles não são vendidos, usados para publicidade ou usados
        para treinar modelos gerais de inteligência artificial.
      </p>

      <h3>3.5. Cobrança e assinatura</h3>
      <p>
        Podemos tratar plano contratado, situação da assinatura, identificadores de
        cliente e cobrança, valor e status de pagamentos. Quando necessário para emitir
        a cobrança, nome, e-mail, telefone e CPF ou CNPJ são enviados ao processador de
        pagamentos. O {LEGAL_NAME} não armazena os dados completos do cartão bancário.
      </p>

      <h3>3.6. Dados técnicos e armazenamento local</h3>
      <p>
        Para funcionamento e segurança, podemos registrar endereço IP, data e hora de
        acesso, rota utilizada, navegador, dispositivo, erros e eventos de segurança. O
        painel utiliza cookie e armazenamento local estritamente necessários para manter
        a sessão, restaurar a navegação e concluir fluxos iniciados pelo próprio usuário.
        Não identificamos, na versão atual, cookies próprios de publicidade ou
        rastreamento comportamental.
      </p>

      <h2 id="finalidades">4. Por que utilizamos os dados</h2>
      <ul>
        <li>autenticar usuários e aplicar as permissões de cada função;</li>
        <li>organizar contatos, células, reuniões, presença e acompanhamento pastoral;</li>
        <li>receber, registrar e responder conversas no WhatsApp oficial;</li>
        <li>sincronizar eventos com a agenda Google escolhida;</li>
        <li>gerar sugestões e respostas assistidas por inteligência artificial;</li>
        <li>enviar convites, recuperação de acesso e avisos operacionais;</li>
        <li>administrar planos, assinaturas e pagamentos;</li>
        <li>prevenir abuso, fraude, acessos indevidos e incidentes de segurança;</li>
        <li>cumprir obrigações legais, regulatórias e ordens de autoridade competente.</li>
      </ul>
      <p>
        As bases legais podem incluir execução de contrato, cumprimento de obrigação
        legal, exercício regular de direitos, legítimo interesse com avaliação de
        necessidade, consentimento e, para dados sensíveis, as hipóteses específicas do
        artigo 11 da LGPD. A base adequada depende da finalidade e do papel exercido pela
        igreja em cada tratamento.
      </p>

      <h2 id="ia">5. Inteligência artificial e decisões humanas</h2>
      <p>
        Se a igreja ativar recursos de IA, trechos de mensagens e contexto estritamente
        necessário podem ser enviados ao provedor configurado para produzir uma resposta
        ou sugestão. Credenciais do provedor são protegidas e não aparecem novamente em
        texto aberto depois de salvas.
      </p>
      <p>
        A IA pode errar e não substitui discernimento pastoral, decisão administrativa,
        aconselhamento profissional ou atendimento de emergência. O sistema foi desenhado
        para limitar ações ao privilégio do interlocutor e manter supervisão humana.
        Pedidos de revisão de decisão automatizada podem ser enviados pelo canal indicado
        nesta política.
      </p>

      <h2 id="compartilhamento">6. Com quem os dados podem ser compartilhados</h2>
      <p>Compartilhamos apenas o necessário com fornecedores que apoiam o serviço:</p>
      <ul>
        <li>
          <strong>Supabase/PostgreSQL e provedores de infraestrutura:</strong>
          banco de dados, armazenamento, filas, hospedagem e segurança;
        </li>
        <li>
          <strong>Clerk:</strong> autenticação e gestão de identidade dos usuários;
        </li>
        <li>
          <strong>Meta/WhatsApp e Evolution API:</strong> conexão e troca de mensagens
          pelo número oficial da igreja;
        </li>
        <li>
          <strong>Google:</strong> autorização da conta e sincronização do Calendar;
        </li>
        <li>
          <strong>OpenAI ou outro provedor configurado:</strong> geração de respostas
          e sugestões quando a igreja ativa a IA;
        </li>
        <li>
          <strong>Asaas:</strong> criação e gestão de cobranças e assinaturas;
        </li>
        <li>
          <strong>Brevo:</strong> envio de convites, redefinições de senha e mensagens
          transacionais;
        </li>
        <li>
          <strong>Vercel e provedores de hospedagem:</strong> entrega do painel e da API.
        </li>
      </ul>
      <p>
        Também podemos compartilhar dados quando exigido por lei ou ordem válida, para
        proteger direitos e segurança, ou em reorganização empresarial com preservação
        das obrigações de confidencialidade. <strong>Não vendemos dados pessoais.</strong>
      </p>

      <h2 id="transferencias">7. Transferências internacionais</h2>
      <p>
        Alguns fornecedores podem processar dados fora do Brasil. Nesses casos, buscamos
        utilizar fornecedores com medidas contratuais, técnicas e organizacionais
        compatíveis com a LGPD. A transferência ocorre apenas para as finalidades
        descritas nesta política e dentro do necessário para prestar o serviço.
      </p>

      <h2 id="retencao">8. Por quanto tempo guardamos os dados</h2>
      <div role="region" aria-label="Períodos de retenção" tabIndex={0}>
        <table>
          <thead>
            <tr>
              <th>Categoria</th>
              <th>Critério de retenção</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>Conta e vínculo com a igreja</td>
              <td>Enquanto o acesso estiver ativo e pelo período necessário para auditoria e obrigações legais.</td>
            </tr>
            <tr>
              <td>Dados pastorais e conversas</td>
              <td>Conforme a finalidade definida pela igreja, solicitações válidas e prazos legais aplicáveis.</td>
            </tr>
            <tr>
              <td>Sessão e redefinição de senha</td>
              <td>Sessões têm duração limitada; links de redefinição expiram em curto prazo.</td>
            </tr>
            <tr>
              <td>Google Calendar</td>
              <td>Enquanto a conexão estiver ativa ou até revogação, desconexão ou exclusão aplicável.</td>
            </tr>
            <tr>
              <td>Registros de acesso</td>
              <td>Ao menos seis meses quando exigido pelo Marco Civil da Internet, com acesso restrito.</td>
            </tr>
            <tr>
              <td>Faturamento</td>
              <td>Pelo prazo necessário ao contrato e às obrigações fiscais, contábeis e de defesa de direitos.</td>
            </tr>
          </tbody>
        </table>
      </div>
      <p>
        Encerrada a finalidade, os dados são eliminados, anonimizados ou mantidos de forma
        restrita quando existir obrigação legal, necessidade de defesa de direitos ou outra
        hipótese permitida pela LGPD. Backups podem permanecer por ciclos limitados até sua
        substituição segura.
      </p>

      <h2 id="seguranca">9. Como protegemos os dados</h2>
      <p>O serviço utiliza medidas proporcionais ao risco, entre elas:</p>
      <ul>
        <li>conexões protegidas por HTTPS/TLS;</li>
        <li>isolamento dos dados por igreja e políticas de acesso no banco;</li>
        <li>controle de permissões por função e autenticação individual;</li>
        <li>criptografia de credenciais e tokens sensíveis armazenados;</li>
        <li>limitação de tentativas, trilhas de auditoria e mascaramento em logs;</li>
        <li>segregação entre ambientes e revisão de segurança do código.</li>
      </ul>
      <p>
        Nenhum sistema é completamente imune a incidentes. Quando houver incidente capaz
        de causar risco ou dano relevante, serão adotadas as medidas de contenção,
        investigação e comunicação exigidas pela legislação.
      </p>

      <h2 id="direitos">10. Direitos dos titulares</h2>
      <p>Nos termos da LGPD, o titular pode solicitar, quando aplicável:</p>
      <ul>
        <li>confirmação da existência de tratamento e acesso aos dados;</li>
        <li>correção de dados incompletos, inexatos ou desatualizados;</li>
        <li>anonimização, bloqueio ou eliminação de dados desnecessários ou irregulares;</li>
        <li>portabilidade, observadas a regulamentação e a proteção de segredos;</li>
        <li>informações sobre compartilhamentos e sobre a possibilidade de negar consentimento;</li>
        <li>revogação do consentimento e eliminação de dados tratados com essa base;</li>
        <li>oposição a tratamento irregular e revisão de decisões automatizadas relevantes.</li>
      </ul>
      <p>
        Pedidos simples serão atendidos de imediato quando possível. Solicitações
        detalhadas de acesso serão respondidas no prazo legal aplicável, que pode chegar a
        15 dias. Podemos pedir informações para confirmar a identidade e evitar que dados
        sejam entregues à pessoa errada.
      </p>
      <p>
        Para dados cadastrados por uma igreja, o pedido pode precisar ser encaminhado à
        própria igreja controladora. Se necessário, informaremos essa circunstância e
        ajudaremos no direcionamento. O titular também pode peticionar perante a
        <a href="https://www.gov.br/anpd/pt-br" rel="noreferrer" target="_blank">
          {" "}Autoridade Nacional de Proteção de Dados (ANPD)
        </a>
        .
      </p>

      <h2 id="criancas">11. Crianças e adolescentes</h2>
      <p>
        Contas administrativas do painel são destinadas a adultos autorizados. Quando a
        igreja registra dados de crianças ou adolescentes em atividades pastorais, deve
        observar o melhor interesse do menor, limitar o acesso e obter o consentimento do
        responsável quando exigido. O serviço não deve ser usado para abordagem comercial
        ou perfilamento inadequado de menores.
      </p>

      <h2 id="cookies">12. Cookies e tecnologias semelhantes</h2>
      <p>
        A versão atual usa apenas mecanismos essenciais de sessão, segurança e continuidade
        de fluxo. Eles não podem ser desativados sem comprometer o login e o funcionamento
        do painel. Se futuramente forem adicionados cookies não essenciais de análise ou
        publicidade, esta política será atualizada e será disponibilizado um mecanismo de
        escolha antes da ativação, quando exigido.
      </p>

      <h2 id="google-revogacao">13. Como desconectar o Google</h2>
      <p>
        Um administrador pode desconectar a agenda no painel, interrompendo o uso da
        conexão pelo {LEGAL_NAME}. Para revogar também a autorização mantida na Conta
        Google, o usuário deve acessar a área de segurança da própria Conta Google e remover
        o acesso do aplicativo. A revogação pode exigir uma nova conexão para voltar a
        sincronizar eventos.
      </p>

      <h2 id="alteracoes">14. Alterações desta política</h2>
      <p>
        Podemos atualizar esta política para refletir mudanças legais, de segurança ou de
        funcionamento. Alterações relevantes serão comunicadas por meio adequado e a data
        no início da página será atualizada. Se uma nova finalidade depender de
        consentimento, ela não será aplicada antes da obtenção desse consentimento.
      </p>

      <h2 id="contato">15. Contato sobre privacidade</h2>
      <p>
        Para dúvidas, reclamações ou exercício de direitos, escreva para
        <a href={`mailto:${LEGAL_CONTACT_EMAIL}`}> {LEGAL_CONTACT_EMAIL}</a>. Informe seu
        nome, a igreja relacionada e o pedido, sem enviar senha, token, chave de API ou
        documentos desnecessários no primeiro contato.
      </p>
      <p>
        Esta política foi preparada com base no funcionamento atual do produto, na
        <a
          href="https://www.planalto.gov.br/ccivil_03/_ato2015-2018/2018/lei/l13709compilado.htm"
          rel="noreferrer"
          target="_blank"
        >
          {" "}Lei Geral de Proteção de Dados
        </a>
        , no
        <a
          href="https://www.planalto.gov.br/ccivil_03/_ato2011-2014/2014/lei/l12965.htm"
          rel="noreferrer"
          target="_blank"
        >
          {" "}Marco Civil da Internet
        </a>
        {" "}e em orientações da ANPD. Ela não substitui avaliação jurídica específica da
        entidade responsável pela operação comercial do serviço.
      </p>
    </LegalDocument>
  );
}
