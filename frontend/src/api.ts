import type { Cuestionario, ExtractionResult } from "./types";

const API_URL = (import.meta.env.VITE_API_URL ?? "http://localhost:8000").replace(/\/+$/, "");

export class ApiError extends Error {
  readonly code: string;
  readonly status?: number;
  readonly requestId?: string | null;

  constructor(code: string, message: string, status?: number, requestId?: string | null) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.status = status;
    this.requestId = requestId;
  }
}

export async function extractQuestionnaire(file: File, signal?: AbortSignal): Promise<ExtractionResult> {
  const body = new FormData();
  body.append("file", file);

  let response: Response;
  try {
    response = await fetch(`${API_URL}/api/v1/questionnaires/extract`, { method: "POST", body, signal });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new ApiError(
      "network_error",
      "No se pudo conectar con el servidor. Revisa tu conexión e inténtalo de nuevo en unos segundos.",
    );
  }

  const requestId = response.headers.get("X-Request-ID");
  if (!response.ok) {
    let code = "http_error";
    let message = `El servidor respondió con un error inesperado (HTTP ${response.status}).`;
    try {
      const payload = await response.json();
      if (payload?.error?.message) {
        code = payload.error.code ?? code;
        message = payload.error.message;
      }
    } catch {
      // El cuerpo no era JSON (p. ej. un error del proxy): se mantiene el mensaje genérico.
    }
    throw new ApiError(code, message, response.status, requestId);
  }

  const data = (await response.json()) as Cuestionario;
  const processing = Number(response.headers.get("X-Processing-Time-Ms"));
  return {
    data,
    fileName: file.name,
    method: response.headers.get("X-Extraction-Method"),
    fallbackReason: response.headers.get("X-Fallback-Reason"),
    classifier: response.headers.get("X-Classifier"),
    processingMs: Number.isFinite(processing) && processing > 0 ? processing : null,
  };
}
