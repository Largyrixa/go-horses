import { useCallback, useEffect, useRef, useState } from "react";
import { api, getToken, wsUrl } from "@/lib/api";

// Sala em tempo real (RF09) com reconexão automática e ressincronização (RF24).
// Mensagens aceitas do servidor (qualquer combinação de campos):
//   { auction, recent_bids, bid, participants, spectators }
//   { type: "chat_history", messages }   histórico do chat ao entrar
//   { type: "chat", message }            nova mensagem do chat
const FATAL_CLOSE = [4401, 4402, 4404]; // sem sessão, saldo insuficiente, leilão inexistente
const MAX_CHAT = 200;

export function useRoom(id, role) {
  const [auction, setAuction] = useState(null);
  const [bids, setBids] = useState([]);
  const [counts, setCounts] = useState({ participants: 0, spectators: 0 });
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState(null);
  const [chat, setChat] = useState([]);
  const [closeCode, setCloseCode] = useState(null);
  const wsRef = useRef(null);

  const apply = useCallback((m) => {
    if (m.auction) setAuction(m.auction);
    if (Array.isArray(m.recent_bids)) setBids(m.recent_bids.slice(0, 20));
    if (m.bid) setBids((prev) => (prev.some((b) => b.id === m.bid.id) ? prev : [m.bid, ...prev].slice(0, 20)));
    if (m.participants != null) setCounts({ participants: m.participants, spectators: m.spectators ?? 0 });
  }, []);

  useEffect(() => {
    if (!id) return;
    let closed = false, ws, retry = 0, timer;
    setCloseCode(null);
    const sync = () =>
      api.room(id).then((r) => { if (!closed) { apply(r); setError(null); } }).catch((e) => { if (!closed) setError(e); });
    const connect = () => {
      ws = new WebSocket(wsUrl(`/auctions/${id}/ws`, { token: getToken(), role }));
      wsRef.current = ws;
      ws.onopen = () => { retry = 0; setConnected(true); setCloseCode(null); sync(); };
      ws.onmessage = (ev) => {
        let m;
        try { m = JSON.parse(ev.data); } catch { return; }
        if (m.type === "chat_history") { setChat(Array.isArray(m.messages) ? m.messages.slice(-MAX_CHAT) : []); return; }
        if (m.type === "chat") {
          setChat((prev) => (prev.some((c) => c.id === m.message.id) ? prev : [...prev, m.message].slice(-MAX_CHAT)));
          return;
        }
        apply(m);
      };
      ws.onerror = () => ws.close();
      ws.onclose = (ev) => {
        setConnected(false);
        if (closed) return;
        if (FATAL_CLOSE.includes(ev.code)) { setCloseCode(ev.code); return; } // não adianta reconectar
        retry += 1;
        timer = setTimeout(connect, Math.min(1000 * 2 ** retry, 8000));
      };
    };
    sync();
    connect();
    return () => { closed = true; clearTimeout(timer); wsRef.current = null; ws && ws.close(); };
  }, [id, role, apply]);

  const sendChat = useCallback((text) => {
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: "chat", text }));
  }, []);

  return { auction, bids, counts, connected, error, push: apply, chat, sendChat, closeCode };
}