import { useEffect, useState } from "react";
import { serverNow } from "@/lib/api";

export function useNow(step = 250) {
  const [now, setNow] = useState(() => serverNow());
  useEffect(() => {
    const id = setInterval(() => setNow(serverNow()), step);
    return () => clearInterval(id);
  }, [step]);
  return now;
}
