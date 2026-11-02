import type { Item } from "../types";
import { TIPO_LABELS, isCorrect } from "../utils";

export function ItemCard({ item }: { item: Item }) {
  const hasAnswer = item.respuesta_correcta !== null;

  return (
    <article className="item-card">
      <header className="item-card__header">
        <span className="item-card__number">{item.numero}</span>
        <span className={`type-badge type-badge--${item.tipo}`}>{TIPO_LABELS[item.tipo]}</span>
      </header>
      <p className="item-card__statement">{item.enunciado}</p>

      {item.alternativas.length > 0 ? (
        <ul className="options">
          {item.alternativas.map((alternativa) => {
            const correct = isCorrect(alternativa.valor, item.respuesta_correcta);
            return (
              <li key={String(alternativa.valor)} className={`option${correct ? " option--correct" : ""}`}>
                <span className="option__value">{alternativa.valor}</span>
                <span className="option__text">{alternativa.texto}</span>
                {correct && <span className="option__tag">Correcta</span>}
              </li>
            );
          })}
        </ul>
      ) : (
        <p className="item-card__open">
          {hasAnswer ? (
            <>
              <strong>Respuesta modelo:</strong> {item.respuesta_correcta}
            </>
          ) : (
            "Respuesta abierta (sin alternativas)"
          )}
        </p>
      )}
    </article>
  );
}
