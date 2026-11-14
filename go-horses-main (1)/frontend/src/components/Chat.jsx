import { useEffect, useRef, useState } from "react";
import { Send } from "lucide-react";
import { fmtTime, maskName } from "@/utils/format";

const MAX = 300;

export default function Chat({ messages, onSend, meId, disabled }) {
  const [text, setText] = useState("");
  const listRef = useRef(null);
  const stick = useRef(true); // só rola para o fim se a pessoa já estava no fim

  useEffect(() => {
    const el = listRef.current;
    if (el && stick.current) el.scrollTop = el.scrollHeight;
  }, [messages]);

  function onScroll(e) {
    const el = e.currentTarget;
    stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
  }

  function submit(e) {
    e.preventDefault();
    const t = text.trim();
    if (!t || disabled) return;
    onSend(t);
    setText("");
    stick.current = true;
  }

  return (
    <div className="panel flex flex-col gap-3">
      <h2 className="text-lg font-bold text-white">Chat ao vivo</h2>
      <ol
        ref={listRef}
        onScroll={onScroll}
        aria-live="polite"
        aria-label="Mensagens do chat"
        className="flex h-72 flex-col gap-2 overflow-y-auto pr-1"
      >
        {messages.length === 0 && <li className="text-gray">Nenhuma mensagem ainda. Diga olá!</li>}
        {messages.map((m) => (
          <li key={m.id} className="break-words text-sm">
            <span className={`font-bold ${m.user?.id === meId ? "text-primary" : "text-white"}`}>
              {m.user?.id === meId ? "Você" : maskName(m.user?.display_name)}
            </span>
            <span className="ml-2 text-xs text-gray">{fmtTime(m.created_at)}</span>
            <p className="text-textColor/90">{m.text}</p>
          </li>
        ))}
      </ol>
      <form onSubmit={submit} className="flex gap-2">
        <input
          className="field py-2"
          value={text}
          maxLength={MAX}
          disabled={disabled}
          onChange={(e) => setText(e.target.value)}
          placeholder={disabled ? "Chat indisponível (sem conexão)" : "Escreva uma mensagem"}
          aria-label="Mensagem"
        />
        <button
          type="submit"
          disabled={disabled || !text.trim()}
          aria-label="Enviar mensagem"
          className="rounded-md border border-primary px-3 text-primary hover:bg-primary hover:text-black disabled:opacity-40"
        >
          <Send size={18} aria-hidden="true" />
        </button>
      </form>
    </div>
  );
}