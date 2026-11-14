import { useCallback, useEffect, useState } from "react";
import { api, getToken, wsUrl } from "@/lib/api";

// Sala em tempo real (RF09) com reconexão automática e ressincronização (RF24).
// Mensagens aceitas do servidor (qualquer combinação de campos):
//   { auction, recent_bids, bid, participants, spectators }
export function useRoom(id, role) {
  const [auction, setAuction] = useState(null);
  const [bids, setBids] = useState([]);
  const [counts, setCounts] = useState({ participants: 0, spectators: 0 });
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState(null);

  const apply = useCallback((m) => {
    if (m.auction) setAuction(m.auction);
    if (Array.isArray(m.recent_bids)) setBids(m.recent_bids.slice(0, 20));
    if (m.bid) setBids((prev) => (prev.some((b) => b.id === m.bid.id) ? prev : [m.bid, ...prev].slice(0, 20)));
    if (m.participants != null) setCounts({ participants: m.participants, spectators: m.spectators ?? 0 });
  }, []);

  useEffect(() => {
    if (!id) return;
    let closed = false, ws, retry = 0, timer;
    const sync = () =>
      api.room(id).then((r) => { if (!closed) { apply(r); setError(null); } }).catch((e) => { if (!closed) setError(e); });
    const connect = () => {
      ws = new WebSocket(wsUrl(`/auctions/${id}/ws`, { token: getToken(), role }));
      ws.onopen = () => { retry = 0; setConnected(true); sync(); };
      ws.onmessage = (ev) => { try { apply(JSON.parse(ev.data)); } catch {} };
      ws.onerror = () => ws.close();
      ws.onclose = () => {
        setConnected(false);
        if (closed) return;
        retry += 1;
        timer = setTimeout(connect, Math.min(1000 * 2 ** retry, 8000));
      };
    };
    sync();
    connect();
    return () => { closed = true; clearTimeout(timer); ws && ws.close(); };
  }, [id, role, apply]);

  return { auction, bids, counts, connected, error, push: apply };
}
