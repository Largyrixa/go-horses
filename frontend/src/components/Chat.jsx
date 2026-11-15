import { useRef, useState } from "react";
import Button from "@/components/Button";
import { fmtTime } from "@/utils/format";

// Chat ao vivo da sala do leilão. As mensagens chegam via WebSocket (useRoom)
// e são efêmeras: ficam em memória no servidor enquanto a sala tem gente.
export default function Chat({ messages = [], connected, currentUserId, onSend }) {
  const [text, setText] = useState("");
  const listRef = useRef(null);

  function submit(e) {
    e.preventDefault();
    const value = text.trim();
    if (!value || !connected) return;
    onSend(value);
    setText("");
  }

  return (
    <div className="panel flex flex-col">
      <h2 className="mb-3 text-lg font-bold text-white">Chat da sala</h2>
      <ol ref={listRef} className="flex max-h-72 flex-col gap-2 overflow-y-auto pr-1">
        {messages.length === 0 ? (
          <li className="text-sm text-gray">Nenhuma mensagem ainda. Diga oi!</li>
        ) : (
          messages.map((m) => (
            <li key={m.id} className="flex flex-col gap-0.5">
              <span className="text-xs text-gray">
                <span className={m.user_id === currentUserId ? "text-primary" : "text-textColor"}>
                  {m.user_id === currentUserId ? "Você" : m.display_name}
                </span>
                {" · "}{fmtTime(m.sent_at)}
              </span>
              <span className="whitespace-pre-wrap break-words text-sm text-textColor/95">{m.text}</span>
            </li>
          ))
        )}
      </ol>
      <form onSubmit={submit} className="mt-3 flex gap-2">
        <input
          className="field"
          value={text}
          maxLength={500}
          placeholder="Escreva uma mensagem…"
          disabled={!connected}
          onChange={(e) => setText(e.target.value)}
        />
        <Button type="submit" variant="solid" disabled={!connected || !text.trim()}>Enviar</Button>
      </form>
    </div>
  );
}
