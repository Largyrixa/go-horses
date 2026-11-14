import { useState } from "react";
import { ImageOff } from "lucide-react";

export default function Gallery({ photos = [], name }) {
  const [i, setI] = useState(0);
  if (!photos.length) return <div className="flex aspect-[4/3] items-center justify-center rounded-lg border border-edge text-gray"><ImageOff aria-label="Sem fotos" /></div>;
  return (
    <div>
      <img src={photos[i]} alt={`${name} — foto ${i + 1} de ${photos.length}`} className="aspect-[4/3] w-full rounded-lg border border-edge bg-black object-contain" />
      <div className="mt-3 flex gap-2 overflow-x-auto">
        {photos.map((p, idx) => (
          <button key={p} onClick={() => setI(idx)} aria-label={`Ver foto ${idx + 1}`} aria-current={idx === i}
            className={`h-16 w-20 flex-none overflow-hidden rounded border ${idx === i ? "border-primary" : "border-edge opacity-70 hover:opacity-100"}`}>
            <img src={p} alt="" className="h-full w-full object-cover" />
          </button>
        ))}
      </div>
    </div>
  );
}
