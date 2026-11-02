import { ERROR_TITLES } from "../utils";

interface Props {
  code: string;
  message: string;
  requestId?: string | null;
  onDismiss: () => void;
}

export function ErrorAlert({ code, message, requestId, onDismiss }: Props) {
  return (
    <div className="alert alert--error" role="alert">
      <div>
        <p className="alert__title">{ERROR_TITLES[code] ?? "Ocurrió un error"}</p>
        <p className="alert__message">{message}</p>
        {requestId && <p className="alert__meta">ID de solicitud: {requestId}</p>}
      </div>
      <button type="button" className="alert__close" onClick={onDismiss} aria-label="Cerrar mensaje">
        ×
      </button>
    </div>
  );
}
