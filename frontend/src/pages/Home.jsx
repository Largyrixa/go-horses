import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import AuctionCard from "@/components/AuctionCard";
import Button from "@/components/Button";
import { Empty, ErrorNote, PageTitle } from "@/components/ui";
import { DEFAULT_CATEGORIES } from "@/utils/format";

const STATUS_FILTER = [
  ["", "Agendados e em andamento"],
  ["scheduled", "Agendados"],
  ["running", "Em andamento"],
  ["sold", "Vendidos"],
  ["unsold", "Encerrados sem lances"],
  ["cancelled", "Cancelados"],
];

// RF20 (listagem pública) + RF21 (busca por nome, categoria e estado, combináveis).
export default function Home() {
  const { user } = useAuth();
  const [q, setQ] = useState("");
  const [category, setCategory] = useState("");
  const [status, setStatus] = useState("");
  const [cats, setCats] = useState(DEFAULT_CATEGORIES);
  const [items, setItems] = useState([]);
  const [page, setPage] = useState(1);
  const [more, setMore] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const reqId = useRef(0);

  // `silent` = atualização de fundo: não liga o "carregando" (que piscava e desabilitava o
  // "Carregar mais" a cada 10 s) e, se falhar, mantém a lista que já está na tela.
  const load = useCallback(async (p, append, silent = false) => {
    const my = ++reqId.current;
    if (!silent) setLoading(true);
    try {
      const r = await api.auctions({ q: q.trim(), category, status, page: p });
      if (my !== reqId.current) return;
      // Ao acrescentar uma página, ignora o que já está na lista: leilões abrem e fecham entre
      // uma página e outra, e o mesmo item repetido duplicava o card.
      setItems((prev) => (append ? [...prev, ...r.items.filter((n) => !prev.some((o) => o.id === n.id))] : r.items));
      setMore(!!r.has_more);
      setPage(p);
      setError(null);
    } catch (e) {
      if (my === reqId.current && !silent) setError(e);
    } finally {
      if (my === reqId.current) setLoading(false);
    }
  }, [q, category, status]);

  useEffect(() => { const t = setTimeout(() => load(1, false), 300); return () => clearTimeout(t); }, [load]);
  useEffect(() => { api.categories().then((c) => Array.isArray(c) && c.length && setCats(c)).catch(() => {}); }, []);
  // Mantém a primeira página fresca: leilões abrem e fecham sozinhos.
  useEffect(() => {
    if (page !== 1) return;
    const id = setInterval(() => load(1, false, true), 10000);
    return () => clearInterval(id);
  }, [load, page]);

  return (
    <>
      <div className="flex flex-wrap items-end justify-between gap-4">
        <PageTitle>Leilões</PageTitle>
        <Button href={user ? "/leiloes/novo" : "/login?next=/leiloes/novo"} variant="solid" className="mb-8">Anunciar um item</Button>
      </div>

      <form role="search" onSubmit={(e) => e.preventDefault()} className="mb-8 grid gap-3 md:grid-cols-[2fr_1fr_1fr]">
        <input className="field" type="search" placeholder="Buscar pelo nome do item" aria-label="Buscar pelo nome" value={q} onChange={(e) => setQ(e.target.value)} />
        <select className="field" aria-label="Categoria" value={category} onChange={(e) => setCategory(e.target.value)}>
          <option value="">Todas as categorias</option>
          {cats.map((c) => <option key={c}>{c}</option>)}
        </select>
        <select className="field" aria-label="Estado do leilão" value={status} onChange={(e) => setStatus(e.target.value)}>
          {STATUS_FILTER.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </select>
      </form>

      <ErrorNote>{error && `Não foi possível carregar os leilões. ${error.message}`}</ErrorNote>

      {!error && !loading && items.length === 0 && (
        <Empty action={<Button href={user ? "/leiloes/novo" : "/login?next=/leiloes/novo"}>Criar o primeiro leilão</Button>}>
          Nenhum leilão encontrado. Limpe os filtros ou crie um.
        </Empty>
      )}
      {loading && items.length === 0 && <p className="text-gray" role="status">Carregando leilões…</p>}

      <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
        {items.map((a) => <AuctionCard key={a.id} a={a} />)}
      </div>

      {more && (
        <div className="mt-8 text-center">
          <Button variant="ghost" disabled={loading} onClick={() => load(page + 1, true)}>Carregar mais</Button>
        </div>
      )}
    </>
  );
}
