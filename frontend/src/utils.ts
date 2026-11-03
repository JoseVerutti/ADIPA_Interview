import type { Cuestionario, TipoItem } from "./types";

export const ACCEPTED_EXTENSIONS = [".pdf", ".docx", ".xlsx"] as const;
// Debe coincidir con MAX_FILE_SIZE_MB del backend (en Vercel, 4 MB por el límite de 4,5 MB por petición).
export const MAX_FILE_SIZE_MB = Number(import.meta.env.VITE_MAX_FILE_SIZE_MB) || 10;

export const TIPO_LABELS: Record<TipoItem, string> = {
  escala_likert: "Escala Likert",
  seleccion_multiple: "Selección múltiple",
  verdadero_falso: "Verdadero / Falso",
  desarrollo: "Desarrollo",
  emparejamiento: "Emparejamiento",
};

export const ERROR_TITLES: Record<string, string> = {
  unsupported_file_type: "Formato no soportado",
  invalid_file: "Archivo inválido",
  file_too_large: "Archivo demasiado grande",
  empty_document: "Documento sin texto",
  document_too_long: "Documento demasiado extenso",
  no_items_detected: "No se detectaron ítems",
  extraction_failed: "No se pudo procesar el documento",
  network_error: "No se pudo contactar con el servidor",
  validation_error: "Solicitud inválida",
};

/** Valida en el navegador lo mismo que valida el backend, para dar feedback inmediato. */
export function validateFile(file: File): { code: string; message: string } | null {
  const extension = file.name.slice(file.name.lastIndexOf(".")).toLowerCase();
  if (!ACCEPTED_EXTENSIONS.includes(extension as (typeof ACCEPTED_EXTENSIONS)[number])) {
    return {
      code: "unsupported_file_type",
      message: `El archivo "${file.name}" no es compatible. Formatos permitidos: PDF, DOCX y XLSX.`,
    };
  }
  if (file.size === 0) return { code: "invalid_file", message: "El archivo está vacío." };
  if (file.size > MAX_FILE_SIZE_MB * 1024 * 1024) {
    return {
      code: "file_too_large",
      message: `El archivo pesa ${formatBytes(file.size)}; el máximo permitido es ${MAX_FILE_SIZE_MB} MB.`,
    };
  }
  return null;
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function languageName(code: string): string {
  if (code === "und") return "No determinado";
  try {
    const name = new Intl.DisplayNames(["es"], { type: "language" }).of(code);
    return name ? name.charAt(0).toUpperCase() + name.slice(1) : code;
  } catch {
    return code;
  }
}

export function methodLabel(method: string | null): string {
  if (!method) return "Desconocido";
  if (method.startsWith("llm:")) return `IA (${method.slice(4)})`;
  return "Reglas (respaldo)";
}

export function classifierLabel(classifier: string | null): string {
  if (!classifier || classifier === "rules") return "Reglas";
  return classifier === "jev" ? "Jev + reglas" : classifier;
}

export function countByType(questionnaire: Cuestionario): [TipoItem, number][] {
  const counts = new Map<TipoItem, number>();
  for (const item of questionnaire.items) counts.set(item.tipo, (counts.get(item.tipo) ?? 0) + 1);
  return [...counts.entries()];
}

export function toJson(questionnaire: Cuestionario): string {
  return JSON.stringify(questionnaire, null, 2);
}

export function downloadJson(questionnaire: Cuestionario, sourceFileName: string): void {
  const baseName = sourceFileName.replace(/\.[^.]+$/, "") || "cuestionario";
  const blob = new Blob([toJson(questionnaire)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `${baseName}.json`;
  link.click();
  URL.revokeObjectURL(url);
}

export function isCorrect(valor: number | string, respuesta: number | string | null): boolean {
  if (respuesta === null) return false;
  return String(respuesta).split(",").includes(String(valor));
}
