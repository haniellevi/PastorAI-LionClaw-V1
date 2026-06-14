"use client";

/**
 * Telas BLOQUEADAS no MVP (#universidade-vida · #capacitacao — delta-019/028).
 *
 * São placeholders locked-em-breve: aparecem no menu (Visão G12) mas não navegam
 * para conteúdo operacional e NÃO fazem nenhuma chamada de API. A estrutura
 * exibida é ilustrativa (modelo oficial), com símbolo de relógio/cinza e banner
 * "em breve", fiel ao estado locked do artifact.
 */
import { Icon } from "@/lib/icons";

type LockedVariant = "universidade-vida" | "capacitacao";

interface LockedConfig {
  title: string;
  intro: string;
  banner: { title: string; body: string };
}

const CONFIG: Record<LockedVariant, LockedConfig> = {
  "universidade-vida": {
    title: "Universidade da Vida",
    intro:
      "Encontro em grupo da consolidação. O acompanhamento de turma, módulos e presença chega numa onda futura.",
    banner: {
      title: "Em breve — Universidade da Vida",
      body: "A estrutura abaixo é o modelo oficial que será configurado quando a feature for liberada. Os números são ilustrativos. A tela permanece bloqueada no MVP.",
    },
  },
  capacitacao: {
    title: "Capacitação Destino",
    intro:
      "Trilha de formação de líderes da igreja. Módulo em desenvolvimento — disponível em uma onda futura.",
    banner: {
      title: "Em breve — módulo da Capacitação Destino",
      body: "A estrutura abaixo é o modelo oficial que será configurado quando a feature for liberada. Os números são ilustrativos. A tela permanece bloqueada no MVP.",
    },
  },
};

const UV_MODULES = [
  "1 · Quem é Jesus",
  "2 · A cruz e a graça",
  "3 · Quebrantamento",
  "4 · Visão e propósito",
  "5 · Encontro com Deus",
];

export function LockedScreen({ variant }: { variant: LockedVariant }) {
  const cfg = CONFIG[variant];

  return (
    <div className="screen" key={variant}>
      <div className="screen-head">
        <div className="titles">
          <h2>{cfg.title}</h2>
          <p>{cfg.intro}</p>
        </div>
        <div className="actions">
          <button
            type="button"
            className="btn btn-primary locked-soon"
            disabled
            aria-disabled
            title="Em breve — bloqueado no MVP"
          >
            <Icon name="clock" />
            <span>Em breve</span>
          </button>
        </div>
      </div>

      <div className="soon-banner">
        <span className="soon-ic">
          <Icon name="clock" />
        </span>
        <div>
          <strong>{cfg.banner.title}</strong>
          <p>{cfg.banner.body}</p>
        </div>
      </div>

      {variant === "capacitacao" ? <CapacitacaoStructure /> : <UvStructure />}
    </div>
  );
}

function UvStructure() {
  return (
    <div className="card card-pad">
      <div className="panel-title" style={{ padding: "0 0 var(--s4)" }}>
        Estrutura da turma — 5 módulos por turma (modelo ilustrativo)
      </div>
      <div className="track">
        {UV_MODULES.map((m, i) => (
          <div className={`stop${i < 2 ? " done" : i === 2 ? " now" : ""}`} key={m}>
            <span className="dot">{i < 2 ? <Icon name="check" /> : i + 1}</span>
            <div>
              <div className="nm">{m}</div>
            </div>
          </div>
        ))}
      </div>
      <div className="lock-note">
        <Icon name="lock" />
        Presença mínima e cronograma definidos pela liderança quando a feature for
        liberada.
      </div>
    </div>
  );
}

function CapacitacaoStructure() {
  return (
    <>
      <div className="card card-pad" style={{ marginBottom: "var(--s4)" }}>
        <div className="panel-title" style={{ padding: "0 0 var(--s4)" }}>
          Estrutura da CD — 6 módulos · 1 livro por módulo · 10 aulas por livro
        </div>
        <div className="cd-levels">
          <div className="cd-level">
            <div className="cd-level-h">
              Nível 1 <span>livros 1 + 2</span>
            </div>
            <div className="cd-book">
              <span className="cd-bk">Livro 1</span>
              <span className="cd-aulas">aulas 1.1 – 1.10</span>
            </div>
            <div className="cd-book">
              <span className="cd-bk">Livro 2</span>
              <span className="cd-aulas">aulas 2.1 – 2.10</span>
            </div>
          </div>
          <div className="cd-level">
            <div className="cd-level-h">
              Nível 2 <span>livros 3 + 4</span>
            </div>
            <div className="cd-book">
              <span className="cd-bk">Livro 3</span>
              <span className="cd-aulas">aulas 3.1 – 3.10</span>
            </div>
            <div className="cd-book">
              <span className="cd-bk">Livro 4</span>
              <span className="cd-aulas">aulas 4.1 – 4.10</span>
              <span className="cd-seal">Apto a Liderar</span>
            </div>
          </div>
          <div className="cd-level">
            <div className="cd-level-h">
              Nível 3 <span>livros 5 + 6</span>
            </div>
            <div className="cd-book">
              <span className="cd-bk">Livro 5</span>
              <span className="cd-aulas">aulas 5.1 – 5.10</span>
            </div>
            <div className="cd-book">
              <span className="cd-bk">Livro 6</span>
              <span className="cd-aulas">aulas 6.1 – 6.10</span>
              <span className="cd-seal ok">Certificado completo</span>
            </div>
          </div>
        </div>
        <div className="lock-note">
          <Icon name="lock" />
          Máximo de 2 módulos ativos por turma · várias turmas em paralelo · nível
          concluído exige &gt;70% de assiduidade.
        </div>
      </div>

      <div className="card card-pad">
        <div className="panel-title" style={{ padding: "0 0 var(--s4)" }}>
          Regras previstas (não implementadas no MVP)
        </div>
        <ul className="cd-rules">
          <li>
            <span className="cd-light g" />
            Semáforo de assiduidade: <strong>&gt;80%</strong> verde ·{" "}
            <strong>60–70%</strong> amarelo · <strong>≤50%</strong> vermelho.
          </li>
          <li>
            <span className="cd-light gray" />
            Nível não iniciado aparece cinza/bloqueado; nível concluído com mais de 70%
            de assiduidade.
          </li>
          <li>
            <span className="cd-light" />
            Professor lança frequência por aula → atualiza o cadastro do discípulo.
          </li>
          <li>
            <span className="cd-light" />
            <strong>4 livros</strong> concluídos = selo <strong>Apto a Liderar</strong>{" "}
            (pode multiplicar) · <strong>6 livros</strong> = Certificado completo da CD.
          </li>
          <li>
            <span className="cd-light" />A Escola de Líderes (formação contínua) será
            detalhada à parte, dentro desta trilha.
          </li>
        </ul>
      </div>
    </>
  );
}
