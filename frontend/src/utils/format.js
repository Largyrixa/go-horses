// Estados do leilão (RN01). As chaves são os códigos esperados do back-end;
// se o seu usar outros nomes, troque só as chaves aqui.
export const STATUS = {
  scheduled: { label: "Agendado", cls: "border-soft text-soft" },
  running: { label: "Em andamento", cls: "border-primary text-primary" },
  sold: { label: "Vendido", cls: "bg-primary border-primary text-black" },
  unsold: { label: "Encerrado sem lances", cls: "border-gray text-gray" },
  cancelled: { label: "Cancelado", cls: "border-danger text-danger" },
};
export const FINAL_STATUS = ["sold", "unsold", "cancelled"];

// Categorias de reserva; a lista oficial vem de GET /categories.
export const DEFAULT_CATEGORIES = ["Eletrônicos", "Casa", "Moda", "Veículos", "Arte e colecionáveis", "Esportes", "Outros"];

// RF08: cancela se Agendado, ou Em andamento sem lances.
export const canCancel = (a) => a.status === "scheduled" || (a.status === "running" && (a.bid_count ?? 0) === 0);

// Dinheiro trafega em centavos inteiros (RF19): nunca há float no caminho.
export const brl = (cents) =>
  new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" }).format((cents ?? 0) / 100);

// Aceita só formatos sem ambiguidade e devolve null no resto (antes "1,234.56" virava R$ 1,23,
// "10,999" virava R$ 10,99 e "-5" virava R$ 5,00, tudo em silêncio):
//   "150"  "150,5"  "150,50"  "1.500"  "1.500,00"   (padrão brasileiro)
//   "150.5"  "150.50"                               (ponto como decimal)
//   "1,500.50"                                      (padrão americano, com centavos)
export const MAX_CENTS = 1_000_000_000; // mesmo teto do back-end (R$ 10 milhões)
export function parseCents(input) {
  const s = String(input ?? "").trim().replace(/^R\$\s*/i, "").replace(/\s+/g, "");
  let int, dec;
  let m;
  if ((m = /^(\d{1,3}(?:\.\d{3})+|\d+)(?:,(\d{1,2}))?$/.exec(s))) { int = m[1].replace(/\./g, ""); dec = m[2]; }
  else if ((m = /^(\d+)\.(\d{1,2})$/.exec(s))) { int = m[1]; dec = m[2]; }
  else if ((m = /^(\d{1,3}(?:,\d{3})+)\.(\d{1,2})$/.exec(s))) { int = m[1].replace(/,/g, ""); dec = m[2]; }
  else return null;
  if (int.length > 9) return null;
  const cents = parseInt(int, 10) * 100 + parseInt(((dec ?? "") + "00").slice(0, 2), 10);
  return cents > MAX_CENTS ? null : cents;
}
export const centsToInput = (c) => `${Math.floor(c / 100)},${String(c % 100).padStart(2, "0")}`;

// Horários chegam em UTC (ISO) e são exibidos no fuso de quem vê (RF19).
export const fmtDateTime = (iso) =>
  iso ? new Intl.DateTimeFormat("pt-BR", { dateStyle: "short", timeStyle: "short" }).format(new Date(iso)) : "—";
export const fmtTime = (iso) =>
  iso ? new Intl.DateTimeFormat("pt-BR", { timeStyle: "medium" }).format(new Date(iso)) : "—";

export function fmtClock(ms) {
  if (ms <= 0) return "00:00";
  const t = Math.floor(ms / 1000);
  const d = Math.floor(t / 86400), h = Math.floor((t % 86400) / 3600), m = Math.floor((t % 3600) / 60), s = t % 60;
  const mm = String(m).padStart(2, "0"), ss = String(s).padStart(2, "0");
  if (d > 0) return `${d}d ${h}h ${mm}min`;
  if (h > 0) return `${h}h ${mm}:${ss}`;
  return `${mm}:${ss}`;
}

// Líder sem expor o nome completo: primeiro nome + inicial do último (RF09).
export function maskName(name = "") {
  const p = String(name).trim().split(/\s+/).filter(Boolean);
  if (!p.length) return "—";
  return p.length > 1 ? `${p[0]} ${p[p.length - 1][0].toUpperCase()}.` : p[0];
}

export const toLocalInput = (d) => {
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
};
export const newKey = () =>
  typeof crypto !== "undefined" && crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(36).slice(2)}`;
export const safeNext = (n) => (n && n.startsWith("/") && !n.startsWith("//") && !n.includes("\\") ? n : "/");
export const plural = (n, one, many) => `${n ?? 0} ${n === 1 ? one : many}`;
