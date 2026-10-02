import Link from "next/link";

export default function NotFound() {
  return (
    <main className="full-loader" aria-label="Página não encontrada">
      <div className="scaffold">
        <h1>Página não encontrada</h1>
        <p>O endereço acessado não existe no painel.</p>
        <Link className="btn btn-primary" style={{ marginTop: "var(--s4)" }} href="/#dashboard">
          Voltar ao painel
        </Link>
      </div>
    </main>
  );
}
