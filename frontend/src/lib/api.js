// Única camada que conhece o back-end. Se o contrato do go-horses for diferente,
// ajuste os caminhos/formatos aqui (e só aqui). Contrato assumido: ver README.
// Padrão "/api": em dev o Vite faz proxy para o back-end (vite.config.js); em produção, o proxy reverso da VM.
const BASE = (import.meta.env.VITE_API_URL || "/api").replace(/\/$/, "");
const TOKEN_KEY = "gh_token";
const TIMEOUT_MS = 10000;

export const getToken = () => { try { return localStorage.getItem(TOKEN_KEY); } catch { return null; } };
export const setToken = (t) => { try { t ? localStorage.setItem(TOKEN_KEY, t) : localStorage.removeItem(TOKEN_KEY); } catch {} };

let onUnauthorized = null;
export const setUnauthorizedHandler = (fn) => { onUnauthorized = fn; };

export class ApiError extends Error {
  constructor(status, body) {
    super(body?.error?.message || body?.message || (status === 0 ? "Sem conexão com o servidor." : `Erro ${status} no servidor.`));
    this.status = status;
    this.code = body?.error?.code || body?.code;
    this.minBid = body?.error?.min_bid ?? body?.min_bid;
  }
}

// RF16: o relógio que vale é o do servidor. Guardamos a diferença só para desenhar a contagem.
// O `server_time` do corpo tem milissegundos; o cabeçalho Date só tem segundos. Depois de uma
// leitura precisa, o Date não sobrescreve mais (alternar entre os dois fazia a contagem "pular").
let clockOffset = 0;
let preciseClock = false;
export const serverNow = () => Date.now() + clockOffset;
function syncClock(res, body) {
  const exact = body?.server_time ? Date.parse(body.server_time) : NaN;
  if (!Number.isNaN(exact)) { clockOffset = exact - Date.now(); preciseClock = true; return; }
  if (preciseClock) return;
  const t = Date.parse(res.headers.get("Date") || "");
  if (!Number.isNaN(t)) clockOffset = t - Date.now();
}

const qs = (o = {}) =>
  Object.entries(o).filter(([, v]) => v !== "" && v != null).map(([k, v]) => `${k}=${encodeURIComponent(v)}`).join("&");

// `auth: false` = chamada que não depende da sessão (login, cadastro, logout): não envia o
// token nem dispara o aviso de "sessão expirou" quando a resposta é 401.
async function request(path, { method = "GET", body, headers = {}, auth = true, token: explicit } = {}) {
  const token = explicit ?? (auth ? getToken() : null);
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), TIMEOUT_MS);
  let res;
  try {
    res = await fetch(`${BASE}${path}`, {
      method, signal: ctrl.signal,
      headers: { ...(body ? { "Content-Type": "application/json" } : {}), ...(token ? { Authorization: `Bearer ${token}` } : {}), ...headers },
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new ApiError(0, null); // rede caiu ou estourou o tempo
  } finally {
    clearTimeout(timer);
  }
  let data = null;
  try { data = res.status === 204 ? null : await res.json(); } catch {}
  syncClock(res, data);
  if (!res.ok) {
    // RF02: sessão expirou. Só vale se o token recusado ainda é o atual (não o de um logout/login no meio).
    if (res.status === 401 && auth && token && token === getToken()) { setToken(null); onUnauthorized?.(); }
    throw new ApiError(res.status, data);
  }
  return data;
}

export function wsUrl(path, params) {
  const origin = `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}`;
  const base = import.meta.env.VITE_WS_URL || (BASE.startsWith("/") ? origin + BASE : BASE.replace(/^http/, "ws"));
  return `${base.replace(/\/$/, "")}${path}?${qs(params)}`;
}

export const api = {
  register: (b) => request("/auth/register", { method: "POST", body: b, auth: false }),
  login: (b) => request("/auth/login", { method: "POST", body: b, auth: false }),
  logout: (token) => request("/auth/logout", { method: "POST", auth: false, token }),
  me: () => request("/auth/me"),
  categories: () => request("/categories"),
  auctions: (params) => request(`/auctions?${qs(params)}`),
  auction: (id) => request(`/auctions/${encodeURIComponent(id)}`),
  createAuction: (b) => request("/auctions", { method: "POST", body: b }),
  updateAuction: (id, patch) => request(`/auctions/${encodeURIComponent(id)}`, { method: "PATCH", body: patch }),
  relistAuction: (id, body) => request(`/auctions/${encodeURIComponent(id)}/relist`, { method: "POST", body }),
  cancelAuction: (id) => request(`/auctions/${encodeURIComponent(id)}/cancel`, { method: "POST" }),
  room: (id) => request(`/auctions/${encodeURIComponent(id)}/room`),
  // RF12: a chave identifica a tentativa; reenviar a mesma chave devolve o resultado original.
  bid: (id, amount, key) => request(`/auctions/${encodeURIComponent(id)}/bids`, { method: "POST", body: { amount }, headers: { "Idempotency-Key": key } }),
  myAuctions: () => request("/me/auctions"),
  myParticipations: () => request("/me/participations"),
  users: (q) => request(`/users?${qs({ q })}`),
  user: (id) => request(`/users/${id}`),
  presign: (b) => request("/uploads/presign", { method: "POST", body: b }),
};

// RF07: a foto vai direto para o armazenamento em nuvem; o back-end só guarda a URL.
export async function uploadPhoto(file) {
  const { upload_url, public_url } = await api.presign({ filename: file.name, content_type: file.type, size: file.size });
  let res;
  try { res = await fetch(upload_url, { method: "PUT", headers: { "Content-Type": file.type }, body: file }); }
  catch { throw new ApiError(0, null); }
  if (!res.ok) throw new ApiError(res.status, { message: `Falha ao enviar ${file.name}.` });
  return public_url;
}
