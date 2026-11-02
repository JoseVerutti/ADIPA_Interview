import { useRef, useState, type DragEvent, type KeyboardEvent } from "react";
import { ACCEPTED_EXTENSIONS, MAX_FILE_SIZE_MB, formatBytes } from "../utils";

interface Props {
  file: File | null;
  disabled: boolean;
  onSelect: (file: File) => void;
  onClear: () => void;
}

export function FileDropzone({ file, disabled, onSelect, onClear }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);

  const openPicker = () => {
    if (!disabled) inputRef.current?.click();
  };

  const handleDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setDragging(false);
    if (disabled) return;
    const dropped = event.dataTransfer.files?.[0];
    if (dropped) onSelect(dropped);
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      openPicker();
    }
  };

  if (file) {
    const extension = file.name.split(".").pop()?.toUpperCase() ?? "";
    return (
      <div className="file-chip">
        <span className={`file-badge file-badge--${extension.toLowerCase()}`}>{extension}</span>
        <div className="file-chip__info">
          <span className="file-chip__name" title={file.name}>
            {file.name}
          </span>
          <span className="file-chip__meta">{formatBytes(file.size)}</span>
        </div>
        <button type="button" className="btn btn--ghost" onClick={onClear} disabled={disabled}>
          Cambiar archivo
        </button>
      </div>
    );
  }

  return (
    <div
      role="button"
      tabIndex={disabled ? -1 : 0}
      aria-disabled={disabled}
      aria-label="Seleccionar archivo PDF, DOCX o XLSX"
      className={`dropzone${dragging ? " dropzone--active" : ""}`}
      onClick={openPicker}
      onKeyDown={handleKeyDown}
      onDragOver={(event) => {
        event.preventDefault();
        setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={handleDrop}
    >
      <svg className="dropzone__icon" viewBox="0 0 24 24" aria-hidden="true">
        <path
          d="M12 16V4m0 0-4 4m4-4 4 4M5 14v4a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-4"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.8"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
      <p className="dropzone__title">
        Arrastra tu cuestionario aquí o <span className="link">selecciónalo</span>
      </p>
      <p className="dropzone__hint">PDF, Word (.docx) o Excel (.xlsx) · máximo {MAX_FILE_SIZE_MB} MB</p>
      <input
        ref={inputRef}
        type="file"
        hidden
        accept={ACCEPTED_EXTENSIONS.join(",")}
        onChange={(event) => {
          const selected = event.target.files?.[0];
          if (selected) onSelect(selected);
          event.target.value = "";
        }}
      />
    </div>
  );
}
