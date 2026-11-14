import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Eye, Users, WifiOff } from "lucide-react";
import { api } from "@/lib/api";
import { useRequireAuth } from "@/lib/auth";
import { useRoom } from "@/lib/useRoom";
import Button from "@/components/Button";
import Countdown from "@/components/Countdown";
import { ErrorNote, StatusBadge } from "@/components/ui";
import { brl, centsToInput, fmtDateTime, fmtTime, maskName, newKey, parseCents } from "@/utils/format";
import { toast } from "@/utils/alerts";

export default function Sala() {
  const { id } = useParams();
  const { user, loading } = useRequireAuth();            // RF04: sala exige login
  const [wantRole, setWantRole] = useState("participant");
  const [roleLocked, setRoleLocked] = useState(false);
  const role = roleLocked ? "spectator" : wantRole;       // comitente só assiste (RF04/RF25)
  const { auction: a, bids, counts, connected, error, push } = useRoom(user ? id : null, role);

  const isSeller = !!(a && user && a.seller?.id === user.id);
  useEffect(() => { setRoleLocked(isSeller); }, [isSeller]);

  // RF26: aviso na hora em que o usuário deixa de ser o líder.
  const wasLeader = useRef(false);
  useEffect(() => {
    if (!a || !user) return;
    const leader = a.leader?.id === user.id;
    if (wasLeader.current && !leader && a.status === "running") toast("warning", `Seu lance foi superado. Novo lance mínimo: ${brl(a.min_bid)}.`);
    wasLeader.current = leader;
  }, [a, user]);

  // Formulário de lance
  const [amount, setAmount] = useState("");
  const [touched, setTouched] = useState(false);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);
  const attempt = useRef(null);                           // { key, cents } — RF12

  useEffect(() => { if (a && !touched) setAmount(centsToInput(a.min_bid)); }, [a?.min_bid, touched]); // eslint-disable-line react-hooks/exhaustive-deps

  async function bid(cents) {
    if (busy) return;                                     // clique duplo não gera segundo envio
    if (cents == null) return setMsg({ err: true, text: "Digite um valor válido, por exemplo 150,00." });
    setBusy(true); setMsg(null);
    if (!attempt.current || attempt.current.cents !== cents) attempt.current = { key: newKey(), cents };
    try {
      const r = await api.bid(id, cents, attempt.current.key);
      attempt.current = null;
      setTouched(false);
      if (r?.auction) push({ auction: r.auction, bid: r.bid });
      setMsg({ text: `Lance de ${brl(cents)} aceito. Você lidera.` });
    } catch (e) {
      if (e.status === 0 || e.status >= 500) {
        // Não sabemos se foi gravado: mantém a chave, e reenviar devolve o resultado original.
        setMsg({ err: true, text: "Não deu para confirmar o lance (falha de conexão). Toque em dar lance de novo: se ele já foi gravado, você recebe o resultado original, sem duplicar." });
      } else {
        attempt.current = null;
        if (e.minBid) { setAmount(centsToInput(e.minBid)); setTouched(false); }
        // A mensagem do backend já traz o valor em R$; só completa quando não traz.
        const showMin = e.minBid && !e.message.includes("R$");
        setMsg({ err: true, text: `${e.message}${showMin ? ` Lance mínimo agora: ${brl(e.minBid)}.` : ""}` });
      }
    } finally {
      setBusy(false);
    }
  }

  if (loading || !user) return <p className="text-gray" role="status">Carregando…</p>;
  if (error && !a) return <ErrorNote>{error.status === 404 ? "Leilão não encontrado." : error.message}</ErrorNote>;
  if (!a) return <p className="text-gray" role="status">Entrando na sala…</p>;

  const running = a.status === "running";
  const price = a.bid_count > 0 ? a.current_price : a.starting_price;
  const iLead = a.leader?.id === user.id;
  const iWon = a.status === "sold" && a.winner?.id === user.id;
  const canBid = running && !isSeller && role === "participant" && connected;

  return (
    <div className="grid gap-8 lg:grid-cols-[1.3fr_1fr]">
      <section aria-label="Estado do leilão" className="flex flex-col gap-5">
        {!connected && (
          <p role="status" className="flex items-center gap-2 rounded-md border border-soft/60 bg-soft/10 px-4 py-3 text-soft">
            <WifiOff size={18} aria-hidden="true" /> Reconectando à sala… o estado atualizado aparece assim que a conexão voltar.
          </p>
        )}

        <div className="flex flex-wrap items-center gap-3">
          <StatusBadge status={a.status} />
          <Link to={`/leiloes/${id}`} className="text-gray underline hover:text-primary">Ver anúncio e fotos</Link>
        </div>
        <h1 className="font-display text-4xl text-white md:text-5xl">{a.name}</h1>

        <div className="panel grid gap-6 sm:grid-cols-2">
          <div>
            <p className="text-sm text-gray">Preço atual</p>
            <p className="font-mono text-4xl text-primary" aria-live="polite">{brl(price)}</p>
            <p className="mt-2 text-sm text-gray">Líder: <span className="text-textColor">{a.bid_count > 0 ? (iLead ? "você" : maskName(a.leader?.display_name)) : "ninguém ainda"}</span></p>
          </div>
          <div>
            <p className="text-sm text-gray">{running ? "Tempo restante" : "Término"}</p>
            <p className="font-mono text-4xl">{running ? <Countdown auction={a} /> : fmtDateTime(a.ends_at)}</p>
            <p className="mt-2 text-sm text-gray">{a.bid_count ?? 0} {a.bid_count === 1 ? "lance" : "lances"}</p>
          </div>
        </div>

        {a.status === "sold" && (
          <p className="rounded-md border border-primary bg-primary/10 px-4 py-4 text-lg" role="status">
            Vendido por <strong>{brl(a.final_price ?? price)}</strong> para <strong>{iWon ? "você" : maskName(a.winner?.display_name)}</strong>.
          </p>
        )}
        {a.status === "unsold" && <p className="rounded-md border border-edge px-4 py-4 text-lg text-gray" role="status">Encerrado sem lances.</p>}
        {a.status === "cancelled" && <p className="rounded-md border border-danger/60 px-4 py-4 text-lg text-danger" role="status">Leilão cancelado pelo comitente.</p>}
        {a.status === "scheduled" && <p className="rounded-md border border-soft/60 px-4 py-4 text-soft">A sala abre em <Countdown auction={a} />, às {fmtDateTime(a.starts_at)}.</p>}

        {running && !isSeller && (
          <div className="flex gap-2" role="group" aria-label="Como você participa">
            <Button variant={wantRole === "participant" ? "solid" : "ghost"} onClick={() => setWantRole("participant")}>Participar</Button>
            <Button variant={wantRole === "spectator" ? "solid" : "ghost"} onClick={() => setWantRole("spectator")}>Só assistir</Button>
          </div>
        )}
        {isSeller && running && <p className="flex items-center gap-2 text-gray"><Eye size={18} aria-hidden="true" /> Você é o comitente: acompanha a sala, mas não dá lances neste leilão.</p>}

        {canBid && (
          <form onSubmit={(e) => { e.preventDefault(); bid(parseCents(amount)); }} className="panel flex flex-col gap-4">
            <label className="block">
              <span className="mb-1.5 block">Seu lance (R$)</span>
              <input className="field font-mono text-xl" inputMode="decimal" value={amount} onChange={(e) => { setAmount(e.target.value); setTouched(true); }} aria-describedby="min-bid" />
              <span id="min-bid" className="mt-1.5 block text-sm text-gray">Lance mínimo atual: <strong className="text-textColor">{brl(a.min_bid)}</strong></span>
            </label>
            {iLead && <p className="text-sm text-primary">Você já lidera este leilão; só pode dar outro lance depois de ser superado.</p>}
            {msg && <p role={msg.err ? "alert" : "status"} className={msg.err ? "text-danger" : "text-primary"}>{msg.text}</p>}
            <div className="flex flex-wrap gap-3">
              <Button type="submit" variant="solid" disabled={busy || iLead}>{busy ? "Enviando…" : "Dar lance"}</Button>
              <Button variant="primary" disabled={busy || iLead} onClick={() => { setTouched(false); setAmount(centsToInput(a.min_bid)); bid(a.min_bid); }}>Dar o mínimo ({brl(a.min_bid)})</Button>
            </div>
            <p className="text-sm text-gray">O lance é irrevogável. O servidor confere o valor mínimo no instante em que processa, não no momento do clique.</p>
          </form>
        )}
      </section>

      <aside aria-label="Últimos lances" className="flex flex-col gap-4">
        <p className="flex items-center gap-4 text-sm text-gray">
          <span className="flex items-center gap-1.5"><Users size={16} aria-hidden="true" /> {counts.participants} participantes</span>
          <span className="flex items-center gap-1.5"><Eye size={16} aria-hidden="true" /> {counts.spectators} espectadores</span>
        </p>
        <div className="panel">
          <h2 className="mb-3 text-lg font-bold text-white">Últimos lances</h2>
          {bids.length === 0 ? (
            <p className="text-gray">Nenhum lance ainda. {running && "O primeiro pode ser igual ao preço inicial."}</p>
          ) : (
            <ol className="flex flex-col divide-y divide-edge">
              {bids.slice(0, 10).map((b, i) => (
                <li key={b.id} className={`flex items-center justify-between gap-3 py-2.5 ${i === 0 ? "text-primary" : ""}`}>
                  <span>{b.bidder?.id === user.id ? "Você" : maskName(b.bidder?.display_name ?? b.bidder_name)}</span>
                  <span className="text-right"><span className="block font-mono">{brl(b.amount)}</span><span className="block text-xs text-gray">{fmtTime(b.created_at)}</span></span>
                </li>
              ))}
            </ol>
          )}
        </div>
      </aside>
    </div>
  );
}
