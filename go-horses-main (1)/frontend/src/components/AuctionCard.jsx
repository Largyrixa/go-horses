import { Link } from "react-router-dom";
import { ImageOff } from "lucide-react";
import { StatusBadge } from "@/components/ui";
import Countdown from "@/components/Countdown";
import { brl } from "@/utils/format";

export default function AuctionCard({ a }) {
  const price = a.bid_count > 0 ? a.current_price : a.starting_price;
  return (
    <Link to={`/leiloes/${a.id}`} className="group flex flex-col overflow-hidden rounded-lg border border-edge bg-surface transition-colors hover:border-primary">
      <div className="aspect-[4/3] bg-black">
        {a.photos?.[0] ? (
          <img src={a.photos[0]} alt={a.name} loading="lazy" className="h-full w-full object-cover" />
        ) : (
          <div className="flex h-full items-center justify-center text-gray"><ImageOff aria-label="Sem foto" /></div>
        )}
      </div>
      <div className="flex flex-1 flex-col gap-2 p-4">
        <div className="flex items-center justify-between gap-2">
          <StatusBadge status={a.status} />
          <span className="truncate text-sm text-gray">{a.category}</span>
        </div>
        <h2 className="line-clamp-2 text-lg font-bold text-white group-hover:text-primary">{a.name}</h2>
        <div className="mt-auto flex items-end justify-between pt-2">
          <div>
            <p className="text-sm text-gray">{a.bid_count > 0 ? "Preço atual" : "Preço inicial"}</p>
            <p className="font-mono text-xl text-primary">{brl(price)}</p>
          </div>
          <Countdown auction={a} className="text-sm text-textColor" />
        </div>
      </div>
    </Link>
  );
}
