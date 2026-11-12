import { useEffect, useState } from "react";
import Tarefa from "./Tarefa.jsx";

// Endereço da API. Local: http://localhost:8000. Em produção vem da variável da Vercel.
const API = import.meta.env.VITE_API_URL || "http://localhost:8000";

export default function App() {
  // ESTADO: dados que mudam. Quando mudam, o React redesenha a tela sozinho.
  const [tarefas, setTarefas] = useState([]);
  const [texto, setTexto] = useState("");
  const [carregando, setCarregando] = useState(true);
  const [erro, setErro] = useState("");
  const [motd, setMotd] = useState("");

  // useEffect com [] roda uma vez, quando a página abre: busca a lista na API.
  useEffect(() => {
    carregar();
  }, []);

  async function carregar() {
    try {
      const resp = await fetch(`${API}/tarefas`);
      if (!resp.ok) throw new Error("A API respondeu com erro");
      setTarefas(await resp.json());
      setErro("");
    } catch (e) {
      setErro("Não consegui falar com a API. Ela está rodando? O CORS está certo?");
    } finally {
      setCarregando(false);
    }
  }

  async function adicionar(evento) {
    evento.preventDefault(); // impede o formulário de recarregar a página
    if (!texto.trim()) return;
    const resp = await fetch(`${API}/tarefas`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ titulo: texto }),
    });
    if (resp.ok) {
      const nova = await resp.json();
      setTarefas([...tarefas, nova]); // nunca altere o estado direto: crie um array novo
      setTexto("");
    }
  }

  async function alternar(tarefa) {
    const resp = await fetch(`${API}/tarefas/${tarefa.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ concluida: !tarefa.concluida }),
    });
    if (resp.ok) {
      const atualizada = await resp.json();
      setTarefas(tarefas.map((t) => (t.id === atualizada.id ? atualizada : t)));
    }
  }

  async function remover(id) {
    const resp = await fetch(`${API}/tarefas/${id}`, { method: "DELETE" });
    if (resp.ok) {
      setTarefas(tarefas.filter((t) => t.id !== id));
    }
  }

  async function atualizarMotd() {
    try {
      const resp = await fetch(`${API}/motd`);
      if (!resp.ok) throw new Error();
      const dados = await resp.json();
      setMotd(dados.texto);
    } catch {
      setMotd("Não consegui buscar a mensagem.");
    }
  }

  const feitas = tarefas.filter((t) => t.concluida).length;

  return (
    <main className="pagina">
      <h1>Go Horses 🐴</h1>
      <p className="sub">
        {carregando ? "Carregando..." : `${feitas} de ${tarefas.length} tarefas concluídas`}
      </p>

      {erro && <p className="erro">{erro}</p>}

      <button onClick={atualizarMotd}>Nova Mensagem</button>
      {motd && <p>{motd}</p>}

      <form onSubmit={adicionar} className="form">
        <input
          value={texto}
          onChange={(e) => setTexto(e.target.value)}
          placeholder="Nova tarefa..."
        />
        <button type="submit">Adicionar</button>
      </form>

      <ul className="lista">
        {tarefas.map((t) => (
          // Cada item da lista precisa de uma key única. Os valores entre {} são as PROPS.
          <Tarefa key={t.id} tarefa={t} aoAlternar={alternar} aoRemover={remover} />
        ))}
      </ul>
    </main>
  );
}
