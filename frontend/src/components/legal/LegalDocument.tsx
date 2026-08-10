import Link from "next/link";
import type { ReactNode } from "react";

import { DiamondMark } from "@/components/brand/DiamondMark";

import { LEGAL_CONTACT_EMAIL, LEGAL_LAST_UPDATED, LEGAL_NAME } from "./legal-config";
import styles from "./legal-document.module.css";

interface LegalDocumentProps {
  children: ReactNode;
  description: string;
  title: string;
}

export function LegalDocument({ children, description, title }: LegalDocumentProps) {
  return (
    <div className={styles.page}>
      <a className={styles.skipLink} href="#conteudo-legal">
        Ir para o conteúdo
      </a>

      <header className={styles.header}>
        <Link className={styles.brand} href="/" aria-label="Voltar ao Igreja 12">
          <span className={styles.brandMark} aria-hidden="true">
            <DiamondMark size={34} title="" />
          </span>
          <span>{LEGAL_NAME}</span>
        </Link>
        <nav className={styles.topNav} aria-label="Documentos legais">
          <Link href="/privacidade">Privacidade</Link>
          <Link href="/termos">Termos de Uso</Link>
          <Link href="/">Entrar no painel</Link>
        </nav>
      </header>

      <main className={styles.main} id="conteudo-legal">
        <section className={styles.hero}>
          <p className={styles.eyebrow}>Transparência e confiança</p>
          <h1>{title}</h1>
          <p>{description}</p>
          <dl className={styles.meta}>
            <div>
              <dt>Última atualização</dt>
              <dd>{LEGAL_LAST_UPDATED}</dd>
            </div>
            <div>
              <dt>Contato</dt>
              <dd>
                <a href={`mailto:${LEGAL_CONTACT_EMAIL}`}>{LEGAL_CONTACT_EMAIL}</a>
              </dd>
            </div>
          </dl>
        </section>

        <article className={styles.document}>{children}</article>
      </main>

      <footer className={styles.footer}>
        <p>© 2026 {LEGAL_NAME}. Todos os direitos reservados.</p>
        <p>
          Estes documentos descrevem o funcionamento atual do serviço e devem ser
          revisados por profissional jurídico habilitado antes de uma expansão comercial.
        </p>
      </footer>
    </div>
  );
}
