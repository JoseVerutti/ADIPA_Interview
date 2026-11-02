export type TipoItem =
  | "escala_likert"
  | "seleccion_multiple"
  | "verdadero_falso"
  | "desarrollo"
  | "emparejamiento";

export interface Alternativa {
  valor: number | string;
  texto: string;
}

export interface Item {
  numero: number;
  enunciado: string;
  tipo: TipoItem;
  alternativas: Alternativa[];
  respuesta_correcta: number | string | null;
}

export interface Cuestionario {
  titulo: string;
  idioma: string;
  total_items: number;
  items: Item[];
}

export interface ExtractionResult {
  data: Cuestionario;
  fileName: string;
  method: string | null;
  fallbackReason: string | null;
  classifier: string | null;
  processingMs: number | null;
}
