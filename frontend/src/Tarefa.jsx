// COMPONENTE: uma função que recebe PROPS e devolve um pedaço de interface.
export default function Tarefa({ tarefa, aoAlternar, aoRemover }) {
  return (
    <li className={tarefa.concluida ? "item feita" : "item"}>
      <label>
        <input
          type="checkbox"
          checked={tarefa.concluida}
          onChange={() => aoAlternar(tarefa)}
        />
        <span>{tarefa.titulo}</span>
      </label>
      <button className="remover" onClick={() => aoRemover(tarefa.id)} aria-label="Remover">
        ✕
      </button>
    </li>
  );
}
