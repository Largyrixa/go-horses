import { useCallback, useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import Button from "@/components/Button";
import Countdown from "@/components/Countdown";
import Gallery from "@/components/Gallery";
import { ErrorNote, StatusBadge } from "@/components/ui";
import { brl, canCancel, fmtDateTime, maskName } from "@/utils/format";
import { confirmDanger, toast } from "@/utils/alerts";

// Detalhe público (RF04: visitante vê tudo, mas só entra na sala logado).
export default function Detalhe() {
  const { id } = useParams();
  const { user } = useAuth();
  const [a, setA] = useState(null);
  const [error, setError] = useState(null);

  const load = useCallback(() => api.auction(id).then((r) => { setA(r); setError(null); }).catch(setError), [id]);
  useEffect(() => { load(); const t = setInterval(load, 5000); return () => clearInterval(t); }, [load]);

  async function cancel() {
    const ok = await confirmDanger({ title: "Cancelar este leilão?", text: "O leilão continua registrado como Cancelado e não pode ser reaberto.", confirmText: "Cancelar leilão" });
    if (!ok) return;
    try { await api.cancelAuction(id); toast("success", "Leilão cancelado."); load(); }
    catch (e) { toast("error", e.message); load(); }
  }

  if (error && !a) return <ErrorNote>{error.status === 404 ? "Leilão não encontrado." : error.message}</ErrorNote>;
  if (!a) return <p className="text-gray" role="status">Carregando…</p>;

  const mine = user && a.seller?.id === user.id;
  const price = a.bid_count > 0 ? a.current_price : a.starting_price;
  const roomHref = `/leiloes/${id}/sala`;

  return (
    <div className="grid gap-10 lg:grid-cols-[1.2fr_1fr]">
      <Gallery photos={a.photos} name={a.name} />

      <div className="flex flex-col gap-5">
        <div className="flex flex-wrap items-center gap-3"><StatusBadge status={a.status} /><span className="text-gray">{a.category}</span></div>
        <h1 className="font-display text-4xl text-white md:text-5xl">{a.name}</h1>
        <p className="whitespace-pre-line text-lg text-textColor/90">{a.description}</p>
        <p className="text-gray">Comitente: <span className="text-textColor">{maskName(a.seller?.display_name)}</span></p>

        <dl className="panel grid grid-cols-2 gap-4">
          <div><dt className="text-sm text-gray">{a.bid_count > 0 ? "Preço atual" : "Preço inicial"}</dt><dd className="font-mono text-2xl text-primary">{brl(price)}</dd></div>
          <div><dt className="text-sm text-gray">Lances</dt><dd className="font-mono text-2xl">{a.bid_count ?? 0}</dd></div>
          <div><dt className="text-sm text-gray">Início</dt><dd>{fmtDateTime(a.starts_at)}</dd></div>
          <div><dt className="text-sm text-gray">Término</dt><dd>{fmtDateTime(a.ends_at)}</dd></div>
          {["scheduled", "running"].includes(a.status) && (
            <div className="col-span-2"><dt className="text-sm text-gray">{a.status === "running" ? "Tempo restante" : "Abertura"}</dt><dd className="text-2xl"><Countdown auction={a} /></dd></div>
          )}
        </dl>

        {a.status === "sold" && <p className="rounded-md border border-primary/60 bg-primary/10 px-4 py-3">Vendido por <strong>{brl(a.final_price ?? price)}</strong>{a.winner && <> para <strong>{maskName(a.winner.display_name)}</strong></>}.</p>}
        {a.status === "unsold" && <p className="rounded-md border border-edge px-4 py-3 text-gray">Encerrado sem lances.</p>}
        {a.status === "cancelled" && <p className="rounded-md border border-danger/60 px-4 py-3 text-danger">Este leilão foi cancelado pelo comitente.</p>}

        <div className="flex flex-wrap gap-3">
          {a.status === "running" && (user
            ? <Button href={roomHref} variant="solid">{mine ? "Acompanhar a sala" : "Entrar na sala"}</Button>
            : <Button href={`/login?next=${encodeURIComponent(roomHref)}`} variant="solid">Entrar para dar lances</Button>)}
          {a.status === "scheduled" && <Button disabled>A sala abre no início</Button>}
          {["sold", "unsold"].includes(a.status) && user && <Button href={roomHref} variant="ghost">Ver sala</Button>}
          {mine && canCancel(a) && <Button variant="danger" onClick={cancel}>Cancelar leilão</Button>}
        </div>
        {mine && a.status === "running" && a.bid_count > 0 && <p className="text-sm text-gray">Leilões com lances não podem ser cancelados.</p>}
      </div>
    </div>
  );
}
