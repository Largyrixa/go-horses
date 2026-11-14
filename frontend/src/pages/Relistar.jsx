import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { ImagePlus, Trash2 } from "lucide-react";
import { api } from "@/lib/api";
import { useRequireAuth } from "@/lib/auth";
import Button from "@/components/Button";
import { Empty, ErrorNote, Field, PageTitle } from "@/components/ui";
import { DEFAULT_CATEGORIES, centsToInput, parseCents, toLocalInput } from "@/utils/format";
import { ALLOWED_TYPES, MAX_MB, MAX_PHOTOS, MIN_PHOTOS, pickPhotos, uploadPhotos } from "@/utils/photos";

// RF28: relista um leilão encerrado sem lances/cancelado, criando outro para o
// mesmo item, com todos os campos editáveis.
export default function Relistar() {
  const { id } = useParams();
  const { user, loading } = useRequireAuth();
  const navigate = useNavigate();

  const [source, setSource] = useState(null);
  const [error, setError] = useState(null);
  const [cats, setCats] = useState(DEFAULT_CATEGORIES);
  const [f, setF] = useState({ name: "", description: "", category: "", price: "", start: "", minutes: "3" });
  const [existing, setExisting] = useState([]);
  const [newPhotos, setNewPhotos] = useState([]);
  const [photoErr, setPhotoErr] = useState("");
  const [busy, setBusy] = useState(false);
  const set = (k) => (e) => setF((p) => ({ ...p, [k]: e.target.value }));

  useEffect(() => {
    api.auction(id).then((a) => {
      setSource(a);
      setF({
        name: a.name,
        description: a.description,
        category: a.category,
        price: centsToInput(a.starting_price),
        start: toLocalInput(new Date(Date.now() + 60000)),
        minutes: "3",
      });
      setExisting(a.photos || []);
    }).catch(setError);
    api.categories().then((c) => Array.isArray(c) && c.length && setCats(c)).catch(() => {});
  }, [id]);

  function addFiles(list) {
    const remaining = Math.max(0, MAX_PHOTOS - existing.length - newPhotos.length);
    const { accepted, errors } = pickPhotos(list, remaining);
    setNewPhotos((p) => [...p, ...accepted]);
    setPhotoErr(errors.join(" "));
  }

  function removeNew(i) {
    setNewPhotos((p) => {
      URL.revokeObjectURL(p[i].url);
      return p.filter((_, j) => j !== i);
    });
  }

  async function submit(e) {
    e.preventDefault();
    setError(null);
    const price = parseCents(f.price);
    const start = new Date(f.start);
    const minutes = Number(f.minutes);
    const total = existing.length + newPhotos.length;

    if (!price || price <= 0) return setError("Informe um preço inicial maior que zero, por exemplo 150,00.");
    if (Number.isNaN(start.getTime())) return setError("Informe a data e a hora de início.");
    if (!(minutes >= 1)) return setError("A duração mínima é de 1 minuto.");
    if (total < MIN_PHOTOS) return setError(`O item precisa de pelo menos ${MIN_PHOTOS} fotos (tem ${total}).`);
    if (total > MAX_PHOTOS) return setError(`O máximo é ${MAX_PHOTOS} fotos.`);

    setBusy(true);
    try {
      const uploaded = await uploadPhotos(newPhotos);
      const a = await api.relistAuction(id, {
        name: f.name.trim(),
        description: f.description.trim(),
        category: f.category,
        photos: [...existing, ...uploaded],
        starting_price: price,
        starts_at: start.toISOString(),
        duration_seconds: Math.round(minutes * 60),
      });
      navigate(`/leiloes/${a.id}`);
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  }

  if (loading || !user) return <p className="text-gray" role="status">Carregando…</p>;
  if (error && !source) return <ErrorNote>{error.status === 404 ? "Leilão não encontrado." : error.message}</ErrorNote>;
  if (!source) return <p className="text-gray" role="status">Carregando leilão…</p>;

  const mine = source.seller?.id === user.id;
  const relistable = ["unsold", "cancelled"].includes(source.status);
  if (!mine || !relistable) {
    return (
      <Empty action={<Button href={`/leiloes/${id}`}>Voltar ao leilão</Button>}>
        {!mine
          ? "Só o comitente pode relistar este leilão."
          : "Só leilões encerrados sem lances ou cancelados podem ser relistados."}
      </Empty>
    );
  }

  const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
  const total = existing.length + newPhotos.length;

  return (
    <div className="mx-auto max-w-3xl">
      <PageTitle>Relistar “{source.name}”</PageTitle>
      <p className="mb-6 text-gray">
        Um novo leilão será criado para o <strong className="text-textColor">mesmo item</strong>. O leilão anterior continua no histórico, sem alterações.
      </p>

      <form onSubmit={submit} className="panel flex flex-col gap-6">
        <Field label="Nome do item"><input className="field" required maxLength={120} value={f.name} onChange={set("name")} /></Field>
        <Field label="Descrição"><textarea className="field min-h-[120px]" required maxLength={2000} value={f.description} onChange={set("description")} /></Field>
        <Field label="Categoria">
          <select className="field" required value={f.category} onChange={set("category")}>
            <option value="">Escolha uma categoria</option>
            {cats.map((c) => <option key={c}>{c}</option>)}
          </select>
        </Field>

        <div className="grid gap-5 md:grid-cols-3">
          <Field label="Preço inicial (R$)" hint="Use vírgula para os centavos."><input className="field" inputMode="decimal" required value={f.price} onChange={set("price")} /></Field>
          <Field label="Início" hint={`Seu fuso: ${tz}`}><input className="field" type="datetime-local" required value={f.start} onChange={set("start")} /></Field>
          <Field label="Duração (minutos)" hint="Mínimo de 1 minuto; máximo de 7 dias."><input className="field" type="number" min="1" max="10080" step="1" required value={f.minutes} onChange={set("minutes")} /></Field>
        </div>
        <div className="-mt-3 flex flex-wrap gap-2" aria-label="Atalhos de horário">
          <Button variant="ghost" onClick={() => setF((p) => ({ ...p, start: toLocalInput(new Date(Date.now() + 60000)) }))}>Abrir em 1 minuto</Button>
          {[3, 10, 60, 1440].map((m) => (
            <Button key={m} variant="ghost" onClick={() => setF((p) => ({ ...p, minutes: String(m) }))}>{m >= 60 ? `${m / 60} h` : `${m} min`}</Button>
          ))}
        </div>

        <fieldset>
          <legend className="mb-1.5 text-base">Fotos <span className="text-gray">({total}/{MAX_PHOTOS}, mínimo {MIN_PHOTOS}; JPG, PNG ou WebP até {MAX_MB} MB)</span></legend>
          <div className="grid grid-cols-3 gap-3 sm:grid-cols-5">
            {existing.map((url, i) => (
              <div key={`${url}-${i}`} className="relative aspect-square overflow-hidden rounded border border-edge">
                <img src={url} alt={`Foto atual ${i + 1}`} className="h-full w-full object-cover" />
                <button type="button" onClick={() => setExisting((p) => p.filter((_, j) => j !== i))} aria-label={`Remover foto ${i + 1}`} className="absolute right-1 top-1 rounded bg-black/80 p-1.5 text-danger hover:bg-danger hover:text-black"><Trash2 size={16} /></button>
              </div>
            ))}
            {newPhotos.map((p, i) => (
              <div key={p.url} className="relative aspect-square overflow-hidden rounded border border-edge">
                <img src={p.url} alt={`Nova foto ${i + 1}`} className="h-full w-full object-cover" />
                <button type="button" onClick={() => removeNew(i)} aria-label={`Remover nova foto ${i + 1}`} className="absolute right-1 top-1 rounded bg-black/80 p-1.5 text-danger hover:bg-danger hover:text-black"><Trash2 size={16} /></button>
              </div>
            ))}
            {total < MAX_PHOTOS && (
              <label className="flex aspect-square cursor-pointer flex-col items-center justify-center gap-1 rounded border border-dashed border-primary/60 text-sm text-primary hover:bg-primary/10 focus-within:outline focus-within:outline-2 focus-within:outline-primary">
                <ImagePlus aria-hidden="true" /> Adicionar
                <input type="file" accept={ALLOWED_TYPES.join(",")} multiple className="sr-only" onChange={(e) => { addFiles(e.target.files); e.target.value = ""; }} />
              </label>
            )}
          </div>
          {photoErr && <p className="mt-2 text-sm text-danger" role="alert">{photoErr}</p>}
        </fieldset>

        <ErrorNote>{error}</ErrorNote>
        <Button type="submit" variant="solid" disabled={busy}>{busy ? "Relistando…" : "Criar novo leilão"}</Button>
      </form>
    </div>
  );
}
