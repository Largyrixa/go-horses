import { useState } from "react";
import { Link } from "react-router-dom";
import { Search } from "lucide-react";
import { api } from "@/lib/api";
import Button from "@/components/Button";
import { Empty, ErrorNote, PageTitle } from "@/components/ui";
import { fmtDateTime } from "@/utils/format";

// RF22: qualquer pessoa busca comitentes pelo nome de exibição.
export default function Comitentes() {
  const [q, setQ] = useState("");
  const [items, setItems] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [searched, setSearched] = useState(false);

  async function search(e) {
    e.preventDefault();
    const term = q.trim();
    if (term.length < 2) {
      setError("Digite pelo menos 2 letras do nome.");
      setItems([]);
      setSearched(false);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const r = await api.users(term);
      setItems(r.items || []);
      setSearched(true);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto max-w-3xl">
      <PageTitle>Comitentes</PageTitle>
      <form role="search" onSubmit={search} className="mb-8 flex flex-col gap-3 sm:flex-row">
        <input
          className="field flex-1"
          type="search"
          placeholder="Buscar pelo nome de exibição"
          aria-label="Buscar comitente pelo nome"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          maxLength={60}
        />
        <Button type="submit" variant="solid" disabled={busy}>
          <Search size={18} aria-hidden="true" /> {busy ? "Buscando…" : "Buscar"}
        </Button>
      </form>

      <ErrorNote>{error}</ErrorNote>

      {searched && items.length === 0 && <Empty>Nenhum comitente encontrado com esse nome.</Empty>}

      <ul className="flex flex-col gap-3">
        {items.map((u) => (
          <li key={u.id}>
            <Link
              to={`/comitentes/${u.id}`}
              className="flex items-center justify-between gap-4 rounded-lg border border-edge bg-surface px-5 py-4 transition-colors hover:border-primary"
            >
              <span className="text-lg text-white">{u.display_name}</span>
              <span className="text-sm text-gray">Membro desde {fmtDateTime(u.created_at)}</span>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
