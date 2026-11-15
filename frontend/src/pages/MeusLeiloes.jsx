import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "@/lib/api";
import { useRequireAuth } from "@/lib/auth";
import Button from "@/components/Button";
import { Empty, ErrorNote, PageTitle, StatusBadge } from "@/components/ui";
import { brl, canCancel, fmtDateTime, plural } from "@/utils/format";
import { confirmDanger, toast } from "@/utils/alerts";

// Leilões do comitente, com cancelamento (RF08).
export default function MeusLeiloes() {
  const { user, loading } = useRequireAuth();
  const [items, setItems] = useState(null);
  const [error, setError] = useState(null);
  const load = useCallback(() => api.myAuctions().then((r) => { setItems(r.items ?? r); setError(null); }).catch(setError), []);
  useEffect(() => { if (user) load(); }, [user, load]);

  async function cancel(a) {
    const ok = await confirmDanger({ title: `Cancelar “${a.name}”?`, text: "O leilão continua registrado como Cancelado.", confirmText: "Cancelar leilão" });
    if (!ok) return;
    try { await api.cancelAuction(a.id); toast("success", "Leilão cancelado."); } catch (e) { toast("error", e.message); }
    load();
  }

  if (loading || !user) return <p className="text-gray" role="status">Carregando…</p>;
  return (
    <>
      <div className="flex flex-wrap items-end justify-between gap-4"><PageTitle>Meus leilões</PageTitle><Button href="/leiloes/novo" variant="solid" className="mb-8">Anunciar um item</Button></div>
      <ErrorNote>{error?.message}</ErrorNote>
      {items && items.length === 0 && <Empty action={<Button href="/leiloes/novo">Criar meu primeiro leilão</Button>}>Você ainda não anunciou nada.</Empty>}
      <ul className="flex flex-col gap-3">
        {(items ?? []).map((a) => (
          <li key={a.id} className="panel flex flex-wrap items-center justify-between gap-4">
            <div className="min-w-0">
              <Link to={`/leiloes/${a.id}`} className="block truncate text-lg font-bold text-white hover:text-primary">{a.name}</Link>
              <p className="mt-1 flex items-center gap-3 text-sm text-gray"><StatusBadge status={a.status} /> {fmtDateTime(a.starts_at)} · {plural(a.bid_count, "lance", "lances")} · {brl(a.bid_count > 0 ? a.current_price : a.starting_price)}</p>
            </div>
            <div className="flex gap-2">
              {a.status === "running" && <Button href={`/leiloes/${a.id}/sala`} variant="ghost">Sala</Button>}
              {canCancel(a) && <Button variant="danger" onClick={() => cancel(a)}>Cancelar</Button>}
            </div>
          </li>
        ))}
      </ul>
    </>
  );
}
