import { useCallback, useEffect, useRef, useState } from "react";
import { api, getToken, wsUrl } from "@/lib/api";

// Sala em tempo real (RF09) com reconexão automática e ressincronização (RF24).
// Mensagens aceitas do servidor (qualquer combinação de campos):
//   { auction, recent_bids, bid, chat, participants, spectators }
//   { type: "chat", message }   (nova mensagem do chat ao vivo)
export function useRoom(id, role) {
  const [auction, setAuction] = useState(null);
  const [bids, setBids] = useState([]);
  const [chat, setChat] = useState([]);
  const [counts, setCounts] = useState({ participants: 0, spectators: 0 });
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState(null);
  const socketRef = useRef(null);

  const apply = useCallback((m) => {
    if (m.auction) setAuction(m.auction);
    if (Array.isArray(m.recent_bids)) setBids(m.recent_bids.slice(0, 20));
    if (m.bid) setBids((prev) => (prev.some((b) => b.id === m.bid.id) ? prev : [m.bid, ...prev].slice(0, 20)));
    if (Array.isArray(m.chat)) setChat(m.chat);
    if (m.type === "chat" && m.message) {
      setChat((prev) => (prev.some((c) => c.id === m.message.id) ? prev : [...prev, m.message].slice(-50)));
    }
    if (m.participants != null) setCounts({ participants: m.participants, spectators: m.spectators ?? 0 });
  }, []);

  const shownId = useRef(id);
  useEffect(() => {
    if (!id) return;
    // Troca de leilão (não de papel): não mostra o estado do anterior enquanto o novo carrega.
    if (shownId.current !== id) {
      shownId.current = id;
      setAuction(null); setBids([]); setChat([]); setCounts({ participants: 0, spectators: 0 }); setError(null);
    }
    let closed = false, ws, retry = 0, timer;
    const sync = () =>
      api.room(id).then((r) => { if (!closed) { apply(r); setError(null); } }).catch((e) => { if (!closed) setError(e); });
    const connect = () => {
      const socket = new WebSocket(wsUrl(`/auctions/${encodeURIComponent(id)}/ws`, { role }));
      ws = socket;
      socketRef.current = socket;
      let ready = false;
      // O token vai na primeira mensagem, não na URL (URLs ficam em logs de acesso).
      socket.onopen = () => socket.send(JSON.stringify({ type: "auth", token: getToken() }));
      socket.onmessage = (ev) => {
        // Só a primeira mensagem do servidor confirma a entrada na sala: o servidor aceita a
        // conexão antes de validar o token, então o `onopen` sozinho não prova nada.
        if (!ready) { ready = true; retry = 0; setConnected(true); sync(); }
        try { apply(JSON.parse(ev.data)); } catch {}
      };
      socket.onerror = () => socket.close();
      socket.onclose = (ev) => {
        if (closed || ws !== socket) return;
        socketRef.current = null;
        setConnected(false);
        // 4401 = sessão inválida, 4404 = leilão inexistente: reconectar não resolve. O `sync`
        // mostra o erro certo (e, no 401, encerra a sessão). Antes isso virava um laço infinito.
        if (ev.code === 4401 || ev.code === 4404) { sync(); return; }
        retry += 1;
        timer = setTimeout(connect, Math.min(1000 * 2 ** retry, 8000));
      };
    };
    sync();
    connect();
    return () => { closed = true; clearTimeout(timer); socketRef.current = null; ws && ws.close(); };
  }, [id, role, apply]);

  const sendChat = useCallback((text) => {
    const s = String(text ?? "").trim();
    if (!s) return;
    const socket = socketRef.current;
    if (socket && socket.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({ type: "chat", text: s }));
    }
  }, []);

  return { auction, bids, chat, counts, connected, error, push: apply, sendChat };
}
