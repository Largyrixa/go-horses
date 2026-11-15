import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "@/lib/api";
import AuctionCard from "@/components/AuctionCard";
import { Empty, ErrorNote, PageTitle } from "@/components/ui";
import { maskName } from "@/utils/format";

const ACTIVE = ["scheduled", "running"];

// RF22: perfil público do comitente — nome, entrada e leilões (ativos/passados).
export default function Perfil() {
  const { id } = useParams();
  const [u, setU] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    setU(null);
    setError(null);
    api.user(id).then(setU).catch(setError);
  }, [id]);

  if (error) return <ErrorNote>{error.status === 404 ? "Comitente não encontrado." : error.message}</ErrorNote>;
  if (!u) return <p className="text-gray" role="status">Carregando perfil…</p>;

  const active = u.auctions.filter((a) => ACTIVE.includes(a.status));
  const past = u.auctions.filter((a) => !ACTIVE.includes(a.status));
  const since = new Intl.DateTimeFormat("pt-BR", { dateStyle: "long" }).format(new Date(u.created_at));

  return (
    <div className="flex flex-col gap-10">
      <header>
        <PageTitle>{u.display_name}</PageTitle>
        <p className="text-gray">
          Membro desde {since} · {u.auctions.length} {u.auctions.length === 1 ? "leilão anunciado" : "leilões anunciados"}
        </p>
      </header>

      <section aria-label="Leilões ativos">
        <h2 className="mb-4 font-display text-2xl text-white">Agendados e em andamento</h2>
        {active.length ? (
          <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
            {active.map((a) => <AuctionCard key={a.id} a={a} />)}
          </div>
        ) : (
          <Empty>Nenhum leilão ativo no momento.</Empty>
        )}
      </section>

      <section aria-label="Leilões encerrados">
        <h2 className="mb-4 font-display text-2xl text-white">Encerrados</h2>
        {past.length ? (
          <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
            {past.map((a) => <AuctionCard key={a.id} a={a} />)}
          </div>
        ) : (
          <Empty>Nenhum leilão encerrado ainda.</Empty>
        )}
      </section>

      <p className="text-sm text-gray">
        No placar da sala, o nome aparece como <strong className="text-textColor">{maskName(u.display_name)}</strong>.
      </p>
    </div>
  );
}
