import { useNow } from "@/lib/clock";
import { fmtClock } from "@/utils/format";

export default function Countdown({ auction, className = "" }) {
  const now = useNow();
  if (!auction) return null;
  const start = Date.parse(auction.starts_at), end = Date.parse(auction.ends_at);
  let text = "—";
  if (auction.status === "scheduled") text = `Abre em ${fmtClock(start - now)}`;
  else if (auction.status === "running") text = end - now <= 0 ? "Encerrando…" : fmtClock(end - now);
  return <span className={`font-mono tabular-nums ${className}`}>{text}</span>;
}
