import { useEffect, useRef, useState } from "react";
import { ApiError, extractQuestionnaire } from "./api";
import { ErrorAlert } from "./components/ErrorAlert";
import { FileDropzone } from "./components/FileDropzone";
import { ResultView } from "./components/ResultView";
import type { ExtractionResult } from "./types";
import { validateFile } from "./utils";

interface UiError {
  code: string;
  message: string;
  requestId?: string | null;
}

const SLOW_REQUEST_MS = 8000;

export default function App() {
  const [file, setFile] = useState<File | null>(null);
  const [loading, setLoading] = useState(false);
  const [slow, setSlow] = useState(false);
  const [error, setError] = useState<UiError | null>(null);
  const [result, setResult] = useState<ExtractionResult | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  // Aviso si la petición tarda: el plan gratuito del servidor "duerme" tras inactividad.
  useEffect(() => {
    if (!loading) return;
    const timer = window.setTimeout(() => setSlow(true), SLOW_REQUEST_MS);
    return () => {
      window.clearTimeout(timer);
      setSlow(false);
    };
  }, [loading]);

  const selectFile = (selected: File) => {
    setResult(null);
    const problem = validateFile(selected);
    if (problem) {
      setFile(null);
      setError(problem);
      return;
    }
    setError(null);
    setFile(selected);
  };

  const process = async () => {
    if (!file) return;
    const controller = new AbortController();
    abortRef.current = controller;
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      setResult(await extractQuestionnaire(file, controller.signal));
    } catch (caught) {
      if (caught instanceof DOMException && caught.name === "AbortError") return;
      if (caught instanceof ApiError) {
        setError({ code: caught.code, message: caught.message, requestId: caught.requestId });
      } else {
        setError({ code: "unknown", message: "Ocurrió un error inesperado. Inténtalo nuevamente." });
      }
    } finally {
      abortRef.current = null;
      setLoading(false);
    }
  };

  const cancel = () => abortRef.current?.abort();

  return (
    <div className="page">
      <header className="hero">
        <h1>Extractor de cuestionarios</h1>
        <p>
          Sube un cuestionario en PDF, Word o Excel y obtén sus ítems, tipos, alternativas y respuestas correctas
          en un JSON estandarizado.
        </p>
      </header>

      <main className="content">
        <section className="card upload" aria-label="Subir documento">
          <FileDropzone
            file={file}
            disabled={loading}
            onSelect={selectFile}
            onClear={() => {
              setFile(null);
              setResult(null);
            }}
          />

          <div className="upload__actions">
            {loading ? (
              <>
                <div className="status" role="status" aria-live="polite">
                  <span className="spinner" aria-hidden="true" />
                  <span>
                    Procesando documento…
                    {slow && (
                      <span className="status__hint">
                        {" "}
                        El servidor puede tardar hasta un minuto si estaba inactivo.
                      </span>
                    )}
                  </span>
                </div>
                <button type="button" className="btn btn--ghost" onClick={cancel}>
                  Cancelar
                </button>
              </>
            ) : (
              <button type="button" className="btn btn--primary btn--lg" onClick={process} disabled={!file}>
                Procesar documento
              </button>
            )}
          </div>
        </section>

        {error && (
          <ErrorAlert
            code={error.code}
            message={error.message}
            requestId={error.requestId}
            onDismiss={() => setError(null)}
          />
        )}

        {result && <ResultView result={result} />}
      </main>

      <footer className="footer">
        Los documentos se procesan en memoria y no se almacenan. Usa solo cuestionarios propios o de dominio
        público.
      </footer>
    </div>
  );
}
