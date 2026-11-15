import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ImagePlus, Trash2 } from "lucide-react";
import { api, uploadPhoto } from "@/lib/api";
import { useRequireAuth } from "@/lib/auth";
import Button from "@/components/Button";
import { ErrorNote, Field, PageTitle } from "@/components/ui";
import { DEFAULT_CATEGORIES, parseCents, toLocalInput } from "@/utils/format";

const MAX_MINUTES = 7 * 24 * 60; // mesmo teto do back-end (7 dias)

const ALLOWED = ["image/jpeg", "image/png", "image/webp"];
const MIN_PHOTOS = Number(import.meta.env.VITE_MIN_PHOTOS || 3);
const MAX_PHOTOS = Number(import.meta.env.VITE_MAX_PHOTOS || 10);
const MAX_MB = Number(import.meta.env.VITE_MAX_PHOTO_MB || 5);

// RF05–RF07: item + leilão numa tela só; fotos vão direto para a nuvem.
export default function NovoLeilao() {
  const { user, loading } = useRequireAuth();
  const navigate = useNavigate();
  const [cats, setCats] = useState(DEFAULT_CATEGORIES);
  const [f, setF] = useState({ name: "", description: "", category: "", price: "", start: "", minutes: "3" });
  const [photos, setPhotos] = useState([]);
  const [photoErr, setPhotoErr] = useState("");
  const [error, setError] = useState(null);
  const [progress, setProgress] = useState("");
  const [busy, setBusy] = useState(false);
  const set = (k) => (e) => setF((p) => ({ ...p, [k]: e.target.value }));

  useEffect(() => {
    setF((p) => ({ ...p, start: toLocalInput(new Date(Date.now() + 60000)) }));
    api.categories().then((c) => Array.isArray(c) && c.length && setCats(c)).catch(() => {});
  }, []);

  // Libera as prévias (blob:) ao sair da tela.
  const photosRef = useRef(photos);
  photosRef.current = photos;
  useEffect(() => () => photosRef.current.forEach((p) => URL.revokeObjectURL(p.url)), []);

  function addFiles(list) {
    const ok = [], errs = [];
    const room = MAX_PHOTOS - photos.length;
    for (const file of Array.from(list)) {
      if (!ALLOWED.includes(file.type)) errs.push(`${file.name}: use JPG, PNG ou WebP.`);
      else if (file.size > MAX_MB * 1048576) errs.push(`${file.name}: passa de ${MAX_MB} MB.`);
      else if (file.size === 0) errs.push(`${file.name}: arquivo vazio.`);
      else if (ok.length >= room) errs.push(`${file.name}: ficou de fora, o limite é de ${MAX_PHOTOS} fotos.`);
      else ok.push({ file, url: URL.createObjectURL(file), uploaded: null });
    }
    setPhotos((p) => [...p, ...ok]);
    setPhotoErr(errs.join(" "));
  }
  function removePhoto(i) {
    if (busy) return; // não mexe na lista durante o envio
    const gone = photos[i];
    if (!gone) return;
    setPhotos((p) => p.filter((x) => x !== gone));
    URL.revokeObjectURL(gone.url);
  }

  async function submit(e) {
    e.preventDefault();
    if (busy) return;
    setError(null);
    const price = parseCents(f.price);
    const start = new Date(f.start);
    const minutes = Number(f.minutes);
    if (!f.name.trim() || !f.description.trim()) return setError("Preencha o nome e a descrição do item.");
    if (!price || price <= 0) return setError("Informe um preço inicial válido e maior que zero, por exemplo 150,00.");
    if (Number.isNaN(start.getTime())) return setError("Informe a data e a hora de início.");
    if (!Number.isInteger(minutes) || minutes < 1) return setError("A duração precisa ser um número inteiro de minutos, no mínimo 1.");
    if (minutes > MAX_MINUTES) return setError("A duração máxima é de 7 dias (10080 minutos).");
    if (photos.length < MIN_PHOTOS) return setError(`Envie pelo menos ${MIN_PHOTOS} fotos (faltam ${MIN_PHOTOS - photos.length}).`);

    setBusy(true);
    try {
      let done = 0;
      setProgress(`Enviando fotos (0 de ${photos.length})…`);
      // Guarda a URL de cada foto já enviada: se algo falhar depois (outra foto, a criação do
      // leilão), tentar de novo não reenvia nem deixa cópias órfãs no servidor.
      const urls = await Promise.all(photos.map(async (p) => {
        if (!p.uploaded) p.uploaded = await uploadPhoto(p.file);
        setProgress(`Enviando fotos (${++done} de ${photos.length})…`);
        return p.uploaded;
      }));
      setProgress("Criando o leilão…");
      const a = await api.createAuction({
        name: f.name.trim(), description: f.description.trim(), category: f.category, photos: urls,
        starting_price: price, starts_at: start.toISOString(), duration_seconds: minutes * 60,
      });
      navigate(`/leiloes/${a.id}`);
    } catch (err) {
      setError(err.message);
      setBusy(false);
      setProgress("");
    }
  }

  if (loading || !user) return <p className="text-gray" role="status">Carregando…</p>;
  const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;

  return (
    <div className="mx-auto max-w-3xl">
      <PageTitle>Anunciar um item</PageTitle>
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
          <Field label="Preço inicial (R$)" hint="Use vírgula para os centavos."><input className="field" inputMode="decimal" required placeholder="150,00" value={f.price} onChange={set("price")} /></Field>
          <Field label="Início" hint={`Seu fuso: ${tz}`}><input className="field" type="datetime-local" required value={f.start} onChange={set("start")} /></Field>
          <Field label="Duração (minutos)" hint="Para a demo, use 3.">
            <input className="field" type="number" min="1" max={MAX_MINUTES} step="1" required value={f.minutes} onChange={set("minutes")} />
          </Field>
        </div>
        <div className="-mt-3 flex flex-wrap gap-2" aria-label="Atalhos de horário">
          <Button variant="ghost" onClick={() => setF((p) => ({ ...p, start: toLocalInput(new Date(Date.now() + 60000)) }))}>Abrir em 1 minuto</Button>
          {[3, 10, 60, 1440].map((m) => (
            <Button key={m} variant="ghost" onClick={() => setF((p) => ({ ...p, minutes: String(m) }))}>{m >= 60 ? `${m / 60} h` : `${m} min`}</Button>
          ))}
        </div>

        <fieldset>
          <legend className="mb-1.5 text-base">Fotos <span className="text-gray">({photos.length}/{MAX_PHOTOS}, mínimo {MIN_PHOTOS}; JPG, PNG ou WebP até {MAX_MB} MB)</span></legend>
          <div className="grid grid-cols-3 gap-3 sm:grid-cols-5">
            {photos.map((p, i) => (
              <div key={p.url} className="relative aspect-square overflow-hidden rounded border border-edge">
                <img src={p.url} alt={`Prévia da foto ${i + 1}`} className="h-full w-full object-cover" />
                <button type="button" onClick={() => removePhoto(i)} aria-label={`Remover foto ${i + 1}`} className="absolute right-1 top-1 rounded bg-black/80 p-1.5 text-danger hover:bg-danger hover:text-black"><Trash2 size={16} /></button>
              </div>
            ))}
            {photos.length < MAX_PHOTOS && (
              <label className="flex aspect-square cursor-pointer flex-col items-center justify-center gap-1 rounded border border-dashed border-primary/60 text-sm text-primary hover:bg-primary/10 focus-within:outline focus-within:outline-2 focus-within:outline-primary">
                <ImagePlus aria-hidden="true" /> Adicionar
                <input type="file" accept={ALLOWED.join(",")} multiple className="sr-only" onChange={(e) => { addFiles(e.target.files); e.target.value = ""; }} />
              </label>
            )}
          </div>
          {photoErr && <p className="mt-2 text-sm text-danger" role="alert">{photoErr}</p>}
        </fieldset>

        <ErrorNote>{error}</ErrorNote>
        {progress && <p className="text-primary" role="status">{progress}</p>}
        <Button type="submit" variant="solid" disabled={busy}>{busy ? "Publicando…" : "Publicar leilão"}</Button>
      </form>
    </div>
  );
}
