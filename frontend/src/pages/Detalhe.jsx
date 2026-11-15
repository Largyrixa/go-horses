import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ImagePlus, Trash2 } from "lucide-react";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import Button from "@/components/Button";
import Countdown from "@/components/Countdown";
import Gallery from "@/components/Gallery";
import { ErrorNote, StatusBadge } from "@/components/ui";
import { brl, canCancel, FINAL_STATUS, fmtDateTime, maskName } from "@/utils/format";
import { ALLOWED_TYPES, MAX_MB, MAX_PHOTOS, pickPhotos, uploadPhotos } from "@/utils/photos";
import { confirmDanger, toast } from "@/utils/alerts";

// Detalhe público (RF04: visitante vê tudo, mas só entra na sala logado).
export default function Detalhe() {
  const { id } = useParams();
  const { user } = useAuth();
  const [a, setA] = useState(null);
  const [error, setError] = useState(null);
  const [editing, setEditing] = useState(false);
  const [editMinutes, setEditMinutes] = useState("");
  const [editPhotos, setEditPhotos] = useState([]);
  const [editErr, setEditErr] = useState("");
  const [editBusy, setEditBusy] = useState(false);

  const current = useRef(id);
  const finished = useRef(false);
  const load = useCallback(() => api.auction(id)
    .then((r) => { if (current.current !== id) return; finished.current = FINAL_STATUS.includes(r.status); setA(r); setError(null); })
    .catch((e) => { if (current.current === id) setError(e); }), [id]);
  useEffect(() => {
    // Outro leilão: limpa o anterior. Leilão em estado final não muda mais, então para de consultar.
    current.current = id; finished.current = false; setA(null); setError(null);
    load();
    const t = setInterval(() => { if (!finished.current) load(); }, 5000);
    return () => clearInterval(t);
  }, [id, load]);

  async function cancel() {
    const ok = await confirmDanger({ title: "Cancelar este leilão?", text: "O leilão continua registrado como Cancelado e não pode ser reaberto.", confirmText: "Cancelar leilão" });
    if (!ok) return;
    try { await api.cancelAuction(id); toast("success", "Leilão cancelado."); load(); }
    catch (e) { toast("error", e.message); load(); }
  }

  function openEditor() {
    const mins = Math.max(1, Math.round((new Date(a.ends_at) - new Date(a.starts_at)) / 60000));
    setEditMinutes(String(mins));
    setEditPhotos([]);
    setEditErr("");
    setEditing(true);
  }

  function addEditFiles(list) {
    const remaining = Math.max(0, MAX_PHOTOS - (a.photos?.length || 0) - editPhotos.length);
    const { accepted, errors } = pickPhotos(list, remaining);
    setEditPhotos((p) => [...p, ...accepted]);
    setEditErr(errors.join(" "));
  }

  async function saveEdit() {
    setEditBusy(true);
    setEditErr("");
    try {
      const body = {};
      if (a.status === "scheduled") {
        const minutes = Number(editMinutes);
        const current = Math.round((new Date(a.ends_at) - new Date(a.starts_at)) / 60000);
        if (!(minutes >= 1)) throw new Error("A duração mínima é de 1 minuto.");
        if (minutes !== current) body.duration_seconds = Math.round(minutes * 60);
      }
      if (editPhotos.length) body.photos = await uploadPhotos(editPhotos);
      if (!Object.keys(body).length) throw new Error("Nada para salvar. Adicione uma foto ou mude a duração.");
      await api.updateAuction(id, body);
      setEditing(false);
      setEditPhotos([]);
      toast("success", "Anúncio atualizado.");
      load();
    } catch (e) {
      setEditErr(e.message);
    } finally {
      setEditBusy(false);
    }
  }

  if (error && !a) return <ErrorNote>{error.status === 404 ? "Leilão não encontrado." : error.message}</ErrorNote>;
  if (!a) return <p className="text-gray" role="status">Carregando…</p>;

  const mine = user && a.seller?.id === user.id;
  const price = a.bid_count > 0 ? a.current_price : a.starting_price;
  const roomHref = `/leiloes/${id}/sala`;
  const canEdit = mine && ["scheduled", "running"].includes(a.status);
  const canRelist = mine && ["unsold", "cancelled"].includes(a.status);

  return (
    <div className="grid gap-10 lg:grid-cols-[1.2fr_1fr]">
      <Gallery photos={a.photos} name={a.name} />

      <div className="flex flex-col gap-5">
        <div className="flex flex-wrap items-center gap-3"><StatusBadge status={a.status} /><span className="text-gray">{a.category}</span></div>
        <h1 className="font-display text-4xl text-white md:text-5xl">{a.name}</h1>
        <p className="whitespace-pre-line text-lg text-textColor/90">{a.description}</p>
        <p className="text-gray">Comitente: <Link to={`/comitentes/${a.seller?.id}`} className="text-textColor underline decoration-soft underline-offset-4 hover:text-primary">{a.seller?.display_name}</Link></p>

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
          {canEdit && <Button variant="ghost" onClick={() => (editing ? setEditing(false) : openEditor())}>{editing ? "Fechar edição" : "Editar anúncio"}</Button>}
          {canRelist && <Button href={`/leiloes/${id}/relistar`} variant="solid">Relistar</Button>}
          {mine && canCancel(a) && <Button variant="danger" onClick={cancel}>Cancelar leilão</Button>}
        </div>
        {mine && a.status === "running" && a.bid_count > 0 && <p className="text-sm text-gray">Leilões com lances não podem ser cancelados.</p>}

        {canEdit && editing && (
          <div className="panel flex flex-col gap-4" aria-label="Editar anúncio">
            <div>
              <h2 className="text-lg font-bold text-white">Editar anúncio</h2>
              <p className="text-sm text-gray">Você pode alterar a duração antes do leilão abrir e apenas <strong className="text-textColor">acrescentar</strong> fotos. Fotos existentes não podem ser removidas ou trocadas.</p>
            </div>

            {a.status === "scheduled" ? (
              <label className="block">
                <span className="mb-1.5 block text-base text-textColor">Duração (minutos)</span>
                <input className="field" type="number" min="1" step="1" value={editMinutes} onChange={(e) => setEditMinutes(e.target.value)} />
              </label>
            ) : (
              <p className="text-sm text-soft">A duração está travada: o leilão já abriu.</p>
            )}

            <div>
              <p className="mb-2 text-sm text-gray">
                Fotos: {a.photos?.length || 0}/{MAX_PHOTOS} · novas nesta edição: {editPhotos.length} · JPG, PNG ou WebP até {MAX_MB} MB
              </p>
              <div className="grid grid-cols-3 gap-3 sm:grid-cols-5">
                {editPhotos.map((p, i) => (
                  <div key={p.url} className="relative aspect-square overflow-hidden rounded border border-edge">
                    <img src={p.url} alt={`Nova foto ${i + 1}`} className="h-full w-full object-cover" />
                    <button type="button" onClick={() => setEditPhotos((list) => { URL.revokeObjectURL(list[i].url); return list.filter((_, j) => j !== i); })} aria-label={`Remover nova foto ${i + 1}`} className="absolute right-1 top-1 rounded bg-black/80 p-1.5 text-danger hover:bg-danger hover:text-black"><Trash2 size={16} /></button>
                  </div>
                ))}
                {(a.photos?.length || 0) + editPhotos.length < MAX_PHOTOS && (
                  <label className="flex aspect-square cursor-pointer flex-col items-center justify-center gap-1 rounded border border-dashed border-primary/60 text-sm text-primary hover:bg-primary/10">
                    <ImagePlus aria-hidden="true" /> Adicionar
                    <input type="file" accept={ALLOWED_TYPES.join(",")} multiple className="sr-only" onChange={(e) => { addEditFiles(e.target.files); e.target.value = ""; }} />
                  </label>
                )}
              </div>
            </div>

            <ErrorNote>{editErr}</ErrorNote>
            <div className="flex gap-3">
              <Button variant="solid" onClick={saveEdit} disabled={editBusy}>{editBusy ? "Salvando…" : "Salvar alterações"}</Button>
              <Button variant="ghost" onClick={() => setEditing(false)} disabled={editBusy}>Cancelar</Button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
