import type { Metadata } from "next";
import Link from "next/link";

import { LegalDocument } from "@/components/legal/LegalDocument";
import { LEGAL_CONTACT_EMAIL, LEGAL_NAME } from "@/components/legal/legal-config";

export const metadata: Metadata = {
  title: "Termos de Uso",
  description:
    "Regras de utilização do Igreja 12 para igrejas, administradores, pastores e líderes autorizados.",
};

export default function TermsPage() {
  return (
    <LegalDocument
      title="Termos de Uso"
      description="Estas regras organizam o uso responsável do painel, das integrações e dos recursos de inteligência artificial do Igreja 12."
    >
      <h2 id="aceite">1. Aceitação</h2>
      <p>
        Ao criar ou ativar uma conta, acessar o painel ou utilizar qualquer integração do
        {" "}{LEGAL_NAME}, você declara que leu e concorda com estes Termos de Uso e com a
        <Link href="/privacidade"> Política de Privacidade</Link>. Se estiver agindo em
        nome de uma igreja ou organização, declara possuir autorização para vinculá-la a
        estes termos.
      </p>
      <p>
        As contas do painel são destinadas a pessoas adultas autorizadas pela igreja. Caso
        não concorde com estas regras, não utilize o serviço e solicite o encerramento do
        acesso ao administrador da sua igreja.
      </p>

      <h2 id="servico">2. O que o serviço oferece</h2>
      <p>
        O {LEGAL_NAME} é uma plataforma de gestão pastoral que reúne pessoas, células,
        reuniões, presença, consolidação, discipulado, agenda, atendimento pelo WhatsApp
        oficial, relatórios, cobrança e recursos assistidos por inteligência artificial.
        Funcionalidades podem variar conforme o plano, as permissões e as integrações
        ativadas pela igreja.
      </p>
      <p>
        Trabalhamos para manter o serviço disponível e seguro, mas não prometemos operação
        ininterrupta. Manutenções, falhas de internet e indisponibilidade de terceiros como
        WhatsApp, Google ou serviços de IA podem afetar temporariamente algumas funções.
      </p>

      <h2 id="contas">3. Contas, acesso e responsabilidades</h2>
      <ul>
        <li>forneça informações corretas e mantenha seus dados atualizados;</li>
        <li>mantenha senha, sessão e dispositivos sob seu controle;</li>
        <li>não compartilhe contas pessoais nem permita acesso a pessoas não autorizadas;</li>
        <li>use somente as funções permitidas para seu papel ministerial;</li>
        <li>comunique imediatamente suspeita de invasão, perda de dispositivo ou uso indevido;</li>
        <li>revise periodicamente quem possui acesso à sua igreja.</li>
      </ul>
      <p>
        A igreja é responsável por cadastrar corretamente seus usuários, escolher
        administradores confiáveis e remover acessos que não sejam mais necessários. Ações
        realizadas por uma conta autenticada podem ser registradas para auditoria e
        segurança.
      </p>

      <h2 id="dados-pastorais">4. Dados pastorais e conteúdo da igreja</h2>
      <p>
        A igreja e os titulares mantêm os direitos sobre os dados, mensagens, documentos e
        demais conteúdos inseridos no serviço. A igreja concede ao {LEGAL_NAME} uma licença
        limitada para hospedar, proteger, processar, transmitir e apresentar esses dados
        somente na medida necessária para operar o serviço e cumprir obrigações legais.
      </p>
      <p>
        Informações religiosas, pedidos de oração, aconselhamento e dados de crianças ou
        adolescentes exigem cuidado reforçado. A igreja deve coletar apenas o necessário,
        definir quem pode acessar e possuir base legal adequada. O painel não autoriza a
        exposição pública ou o uso comercial desses dados.
      </p>

      <h2 id="whatsapp">5. WhatsApp e comunicação</h2>
      <p>
        O serviço deve ser conectado somente a um número oficial controlado pela igreja.
        Conversas pessoais de pastores e líderes não devem ser conectadas ou importadas.
        A igreja é responsável pelo conteúdo das mensagens enviadas, pelo respeito às
        preferências dos contatos e pela interrupção de mensagens quando houver pedido de
        saída ou oposição válida.
      </p>
      <p>
        É proibido usar o serviço para spam, compra de listas, perseguição, fraude,
        desinformação, comunicação ilegal ou envio em massa incompatível com as regras do
        WhatsApp e com a legislação aplicável.
      </p>

      <h2 id="ia">6. Inteligência artificial</h2>
      <p>
        Recursos de IA auxiliam na redação, triagem e organização do trabalho pastoral.
        Eles podem produzir respostas incorretas, incompletas ou inadequadas. O usuário
        deve revisar o resultado antes de tomar decisões ou enviar comunicações relevantes.
      </p>
      <p>
        A IA não substitui liderança pastoral, aconselhamento jurídico, psicológico,
        médico ou atendimento de emergência. Não utilize o sistema para diagnosticar,
        prescrever tratamento, lidar sozinho com risco de vida ou tomar decisão que produza
        efeito jurídico relevante sem análise humana adequada.
      </p>
      <p>
        A igreja deve configurar somente credenciais de provedor que tenha autorização para
        usar. O uso do provedor também está sujeito aos termos e às políticas dele.
      </p>

      <h2 id="google">7. Google Calendar</h2>
      <p>
        Um administrador pode conectar uma conta Google autorizada para sincronizar eventos.
        Antes da conexão, deve conferir se a conta declarada é a correta e se possui direito
        de utilizar a agenda em nome da igreja. Não conecte conta pessoal quando a intenção
        for gerir uma agenda institucional, salvo decisão consciente e autorizada da igreja.
      </p>
      <p>
        O uso dos dados do Google é limitado à sincronização solicitada e observa a
        <a
          href="https://developers.google.com/terms/api-services-user-data-policy"
          rel="noreferrer"
          target="_blank"
        >
          {" "}Política de Dados do Usuário dos Serviços de API do Google
        </a>
        , incluindo os requisitos de Uso Limitado. O usuário pode desconectar a agenda no
        painel e também remover o acesso diretamente nas configurações da Conta Google.
      </p>

      <h2 id="pagamentos">8. Planos, cobrança e cancelamento</h2>
      <p>
        Preços, taxa de configuração, ciclo de cobrança e itens incluídos são os apresentados
        na oferta, no checkout ou no instrumento de contratação vigente. Pagamentos podem
        ser processados pelo Asaas, sujeito também aos termos e políticas desse fornecedor.
      </p>
      <p>
        Assinaturas recorrentes permanecem ativas até cancelamento ou encerramento. Falta de
        pagamento pode resultar em aviso, limitação ou suspensão do acesso, respeitados o
        contrato e a legislação aplicável. Cancelamentos e reembolsos seguirão a oferta
        aceita, a natureza da contratação e os direitos obrigatórios que não podem ser
        afastados por estes termos.
      </p>
      <p>
        A suspensão por cobrança não significa eliminação imediata dos dados. A igreja deve
        solicitar exportação ou encerramento conforme os canais disponibilizados e os prazos
        legais de retenção.
      </p>

      <h2 id="uso-proibido">9. Usos proibidos</h2>
      <p>Não é permitido:</p>
      <ul>
        <li>violar lei, direito de terceiro, sigilo pastoral ou regra de proteção de dados;</li>
        <li>acessar outra igreja, conta ou informação sem autorização;</li>
        <li>tentar contornar autenticação, permissões, limites ou medidas de segurança;</li>
        <li>inserir malware, realizar ataques, varreduras ou testes sem autorização expressa;</li>
        <li>copiar, revender, descompilar ou explorar o serviço fora das permissões legais;</li>
        <li>usar automação para assediar pessoas ou ignorar pedido de interrupção;</li>
        <li>inserir conteúdo ilegal, discriminatório, abusivo ou que viole direitos autorais;</li>
        <li>usar dados de Google, WhatsApp ou membros para publicidade não autorizada.</li>
      </ul>

      <h2 id="propriedade">10. Propriedade intelectual</h2>
      <p>
        O software, a identidade visual, a documentação e os componentes do {LEGAL_NAME}
        pertencem a seus titulares e são protegidos pela legislação. O contrato concede à
        igreja uma autorização limitada, não exclusiva e revogável para utilizar o serviço
        durante a vigência da relação, sem transferir a propriedade da tecnologia.
      </p>
      <p>
        Feedback e sugestões podem ser utilizados para melhorar o produto sem revelar
        informações confidenciais nem transferir a propriedade dos dados pastorais.
      </p>

      <h2 id="terceiros">11. Serviços de terceiros</h2>
      <p>
        Algumas funções dependem de Clerk, Supabase, Vercel, provedores de hospedagem,
        WhatsApp/Meta, Evolution API, Google, OpenAI, Asaas e Brevo. Cada fornecedor possui
        seus próprios termos, disponibilidade e práticas. Não controlamos interrupções ou
        mudanças realizadas por esses terceiros, mas buscamos integrar fornecedores
        adequados e limitar o compartilhamento ao necessário.
      </p>

      <h2 id="suspensao">12. Suspensão e encerramento</h2>
      <p>
        Podemos restringir ou suspender acesso para proteger pessoas e dados, responder a
        incidente, cumprir ordem legal, tratar inadimplência ou interromper uso incompatível
        com estes termos. Quando for razoável e seguro, comunicaremos a causa e ofereceremos
        oportunidade de correção.
      </p>
      <p>
        A igreja pode solicitar encerramento conforme o contrato. Após o encerramento, o
        acesso cessa e os dados serão eliminados, devolvidos, anonimizados ou retidos de
        forma restrita conforme a Política de Privacidade, obrigações legais e necessidade
        de defesa de direitos.
      </p>

      <h2 id="garantias">13. Limites e responsabilidades</h2>
      <p>
        O serviço é fornecido com esforços razoáveis de qualidade e segurança. Na extensão
        permitida pela lei, não respondemos por falhas causadas por uso indevido, credenciais
        comprometidas, informações incorretas inseridas pela igreja, indisponibilidade de
        terceiros, caso fortuito ou força maior.
      </p>
      <p>
        Nada nestes termos exclui responsabilidade que a legislação brasileira não permita
        limitar, incluindo direitos obrigatórios de consumidores quando aplicáveis. Cada
        parte responde pelos danos que causar por ação ou omissão ilícita dentro de sua
        esfera de controle.
      </p>

      <h2 id="confidencialidade">14. Confidencialidade e segurança pastoral</h2>
      <p>
        Usuários devem preservar o sigilo de mensagens, relatórios e informações pastorais.
        É proibido exportar, fotografar, compartilhar ou utilizar dados fora das finalidades
        autorizadas pela igreja. O dever de confidencialidade continua mesmo após a remoção
        do acesso.
      </p>

      <h2 id="alteracoes">15. Mudanças no serviço e nestes termos</h2>
      <p>
        Podemos atualizar funções e estes termos para acompanhar o produto, a legislação e
        requisitos de segurança. Mudanças relevantes serão comunicadas de maneira adequada.
        Quando uma alteração exigir novo consentimento ou aceite, ela não será aplicada ao
        usuário antes dessa manifestação.
      </p>

      <h2 id="lei">16. Lei aplicável e solução de conflitos</h2>
      <p>
        Estes termos são regidos pelas leis da República Federativa do Brasil. Antes de
        iniciar disputa judicial, as partes devem tentar uma solução de boa-fé pelo canal de
        contato durante prazo razoável. Permanecem preservados o foro legalmente competente
        e, quando houver relação de consumo, o direito do consumidor de recorrer ao foro que
        a lei lhe assegurar.
      </p>

      <h2 id="geral">17. Disposições gerais</h2>
      <p>
        Se uma disposição for considerada inválida, as demais continuam vigentes. A falta de
        cobrança imediata de uma obrigação não significa renúncia. A igreja não pode ceder
        seu acesso ou contrato sem autorização, exceto quando permitido no instrumento de
        contratação. Comunicações eletrônicas enviadas aos contatos cadastrados são válidas
        para assuntos operacionais do serviço.
      </p>

      <h2 id="contato">18. Contato</h2>
      <p>
        Dúvidas sobre estes termos podem ser enviadas para
        <a href={`mailto:${LEGAL_CONTACT_EMAIL}`}> {LEGAL_CONTACT_EMAIL}</a>. Para pedidos
        sobre dados pessoais, consulte também a <Link href="/privacidade">Política de Privacidade</Link>.
      </p>
      <p>
        Estes termos foram preparados a partir do funcionamento atual do produto e da
        legislação brasileira aplicável, incluindo LGPD e Marco Civil da Internet. Eles não
        substituem revisão jurídica específica da entidade responsável pela contratação e
        operação comercial do serviço.
      </p>
    </LegalDocument>
  );
}
