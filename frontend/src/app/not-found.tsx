import Link from "next/link";

export default function NotFound() {
  return (
    <div className="full-loader">
      <div className="scaffold">
        <h3>Página não encontrada</h3>
        <p>O endereço acessado não existe no painel.</p>
        <Link className="btn btn-primary" style={{ marginTop: "var(--s4)" }} href="/#dashboard">
          Voltar ao painel
        </Link>
      </div>
    </div>
  );
}
