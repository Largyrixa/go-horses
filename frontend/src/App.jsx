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
  const [motd, setMotd] = useState("\n");
  const [mostrandoForm, setMostrandoForm] = useState(false);
  const [novaMotd, setNovaMotd] = useState("");

  // useEffect com [] roda uma vez, quando a página abre: busca a lista na API.
  useEffect(() => {
    carregar();
  }, []);

  async function carregar() {
    try {
      const resp = await fetch(`${API}/tarefas`);
      if (!resp.ok) throw new Error("A API respondeu com erro");
      const respMotd = await fetch(`${API}/motd`);
      if (!resp.ok) throw new Error();
      setTarefas(await resp.json());
      setMotd((await respMotd.json()).texto)
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

  async function addMotd(evento) {
    evento.preventDefault();
    if (!novaMotd.trim()) return;

    try {
      const resp = await fetch(`${API}/motd`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ texto: novaMotd }),
      });
      if (!resp.ok) throw new Error();
      const criada = await resp.json();
      setMotd(criada.texto);
      setNovaMotd("");
      setMostrandoForm(false);
    } catch {
      setMotd("Não consegui adicionar a mensagem.");
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

      <div className="motd">
        <div className="motd-botoes">
          <button onClick={atualizarMotd}>Nova Mensagem</button>
          <button className="secundario" onClick={() => setMostrandoForm(!mostrandoForm)}>
            {mostrandoForm ? "Cancelar": "+ Adicionar"}
          </button>
        </div>
        <p>{motd || "Clique para ver uma mensagem"}</p>

        {mostrandoForm && (
          <form onSubmit={addMotd} className="form">
            <input
              value={novaMotd}
              onChange={(e) => setNovaMotd(e.target.value)}
              placeholder="Escreva sua mensagem..."
              autoFocus
            />
            <button type="submit">Salvar</button>
          </form>
        )}
      </div>

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
