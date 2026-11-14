import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "@/lib/api";
import { useRequireAuth } from "@/lib/auth";
import Button from "@/components/Button";
import Countdown from "@/components/Countdown";
import { Empty, ErrorNote, PageTitle, StatusBadge } from "@/components/ui";
import { brl } from "@/utils/format";

const SITUATION = {
  leader: { label: "Líder", cls: "border-primary text-primary" },
  outbid: { label: "Superado", cls: "border-danger text-danger" },
  won: { label: "Vencedor", cls: "bg-primary border-primary text-black" },
};

// RF27: leilões em que o usuário deu lances e sua situação em cada um.
export default function Participacoes() {
  const { user, loading } = useRequireAuth();
  const [items, setItems] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!user) return;
    const load = () => api.myParticipations().then((r) => setItems(r.items ?? r)).catch(setError);
    load();
    const t = setInterval(load, 8000);
    return () => clearInterval(t);
  }, [user]);

  if (loading || !user) return <p className="text-gray" role="status">Carregando…</p>;
  return (
    <>
      <PageTitle>Minhas participações</PageTitle>
      <ErrorNote>{error?.message}</ErrorNote>
      {items && items.length === 0 && <Empty action={<Button href="/">Ver leilões abertos</Button>}>Você ainda não deu nenhum lance.</Empty>}
      <ul className="flex flex-col gap-3">
        {(items ?? []).map(({ auction: a, situation, my_top_bid }) => {
          const s = SITUATION[situation];
          return (
            <li key={a.id} className="panel flex flex-wrap items-center justify-between gap-4">
              <div className="min-w-0">
                <Link to={`/leiloes/${a.id}`} className="block truncate text-lg font-bold text-white hover:text-primary">{a.name}</Link>
                <div className="mt-1 flex items-center gap-3 text-sm text-gray"><StatusBadge status={a.status} /> {a.status === "running" && <Countdown auction={a} />}</div>
              </div>
              <div className="text-right">
                {s && <span className={`inline-block rounded border px-2.5 py-0.5 font-mono text-xs ${s.cls}`}>{s.label}</span>}
                <p className="mt-1 font-mono">{brl(a.bid_count > 0 ? a.current_price : a.starting_price)}</p>
                <p className="text-xs text-gray">seu maior lance: {brl(my_top_bid)}</p>
              </div>
              {a.status === "running" && <Button href={`/leiloes/${a.id}/sala`} variant="solid">Ir para a sala</Button>}
            </li>
          );
        })}
      </ul>
    </>
  );
}
