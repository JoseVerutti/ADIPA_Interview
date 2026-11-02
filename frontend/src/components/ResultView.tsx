import { useState } from "react";
import type { ExtractionResult } from "../types";
import { TIPO_LABELS, countByType, downloadJson, languageName, methodLabel, toJson } from "../utils";
import { ItemCard } from "./ItemCard";

type Tab = "items" | "json";

export function ResultView({ result }: { result: ExtractionResult }) {
  const [tab, setTab] = useState<Tab>("items");
  const [copied, setCopied] = useState(false);
  const { data } = result;
  const usedFallback = result.method === "heuristic";

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(toJson(data));
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  };

  return (
    <section className="card result" aria-labelledby="result-title">
      <div className="result__head">
        <div>
          <p className="eyebrow">Resultado · {result.fileName}</p>
          <h2 id="result-title" className="result__title">
            {data.titulo}
          </h2>
        </div>
        <div className="result__actions">
          <button type="button" className="btn btn--secondary" onClick={copy}>
            {copied ? "¡Copiado!" : "Copiar JSON"}
          </button>
          <button type="button" className="btn btn--primary" onClick={() => downloadJson(data, result.fileName)}>
            Descargar JSON
          </button>
        </div>
      </div>

      <dl className="stats">
        <div className="stat">
          <dt>Ítems</dt>
          <dd>{data.total_items}</dd>
        </div>
        <div className="stat">
          <dt>Idioma</dt>
          <dd>
            {languageName(data.idioma)} <span className="muted">({data.idioma})</span>
          </dd>
        </div>
        <div className="stat">
          <dt>Extracción</dt>
          <dd>{methodLabel(result.method)}</dd>
        </div>
        {result.processingMs !== null && (
          <div className="stat">
            <dt>Tiempo</dt>
            <dd>{(result.processingMs / 1000).toFixed(1)} s</dd>
          </div>
        )}
      </dl>

      <div className="type-summary">
        {countByType(data).map(([tipo, count]) => (
          <span key={tipo} className={`type-badge type-badge--${tipo}`}>
            {TIPO_LABELS[tipo]} · {count}
          </span>
        ))}
      </div>

      {usedFallback && (
        <div className="alert alert--warning" role="status">
          <p className="alert__message">
            El servicio de IA no estuvo disponible, así que se usó el extractor basado en reglas. Revisa el
            resultado; volver a intentarlo más tarde puede dar una extracción más precisa.
          </p>
        </div>
      )}

      <div className="tabs" role="tablist" aria-label="Vista del resultado">
        <button
          type="button"
          role="tab"
          aria-selected={tab === "items"}
          className={`tab${tab === "items" ? " tab--active" : ""}`}
          onClick={() => setTab("items")}
        >
          Ítems
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === "json"}
          className={`tab${tab === "json" ? " tab--active" : ""}`}
          onClick={() => setTab("json")}
        >
          JSON
        </button>
      </div>

      {tab === "items" ? (
        <div className="items" role="tabpanel">
          {data.items.map((item) => (
            <ItemCard key={item.numero} item={item} />
          ))}
        </div>
      ) : (
        <pre className="json-view" role="tabpanel" tabIndex={0}>
          <code>{toJson(data)}</code>
        </pre>
      )}
    </section>
  );
}
