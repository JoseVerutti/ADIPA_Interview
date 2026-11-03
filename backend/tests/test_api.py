"""Tests de integración del endpoint (controlador + servicios), con el LLM simulado."""

from app.core.exceptions import LLMRateLimitError
from app.schemas.questionnaire import Cuestionario
from tests.conftest import FakeLLMClient
from tests.factories import SAMPLE_PDF_LINES, docx_bytes, pdf_bytes, xlsx_bytes

ENDPOINT = "/api/v1/questionnaires/extract"
PDF_MIME = "application/pdf"


def upload(client, filename: str, content: bytes, mime: str = "application/octet-stream"):
    return client.post(ENDPOINT, files={"file": (filename, content, mime)})


def test_health(make_client):
    response = make_client().get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_extracts_with_llm_and_returns_the_standard_schema(make_client, spec_example):
    llm_output = {key: value for key, value in spec_example.items() if key != "total_items"}
    client = make_client(FakeLLMClient(llm_output))

    response = upload(client, "questionario.pdf", pdf_bytes(SAMPLE_PDF_LINES), PDF_MIME)

    assert response.status_code == 200, response.text
    assert response.headers["X-Extraction-Method"] == "llm:fake"
    assert "X-Request-ID" in response.headers
    assert Cuestionario.model_validate(response.json())
    assert response.json() == spec_example


def test_falls_back_to_heuristic_when_llm_is_rate_limited(make_client, spec_example):
    client = make_client(FakeLLMClient(LLMRateLimitError("429")))

    response = upload(client, "questionario.pdf", pdf_bytes(SAMPLE_PDF_LINES), PDF_MIME)

    assert response.status_code == 200, response.text
    assert response.headers["X-Extraction-Method"] == "heuristic"
    assert response.headers["X-Fallback-Reason"] == "llm_rate_limited"
    assert response.json() == spec_example


def test_llm_failure_without_fallback_returns_502(make_client):
    client = make_client(FakeLLMClient(LLMRateLimitError("429")), heuristic_fallback=False)
    response = upload(client, "questionario.pdf", pdf_bytes(SAMPLE_PDF_LINES), PDF_MIME)
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "extraction_failed"


def test_processes_docx_and_xlsx_without_llm(make_client):
    client = make_client()
    docx = docx_bytes(["Cuestionario", "1. ¿Capital de Chile?", "a) Lima", "b) Santiago", "Respuesta: b"])
    xlsx = xlsx_bytes([["N°", "Pregunta", "A", "B", "Respuesta"], [1, "¿2+2?", 4, 5, "A"]])

    docx_response = upload(client, "cuestionario.docx", docx)
    xlsx_response = upload(client, "cuestionario.xlsx", xlsx)

    assert docx_response.status_code == 200
    assert docx_response.json()["items"][0]["respuesta_correcta"] == "B"
    assert xlsx_response.status_code == 200
    assert xlsx_response.json()["items"][0]["respuesta_correcta"] == "A"


def test_unsupported_format_returns_415_with_error_body(make_client):
    response = upload(make_client(), "notas.txt", b"1. Hola")
    assert response.status_code == 415
    body = response.json()
    assert body["error"]["code"] == "unsupported_file_type"
    assert "PDF, DOCX y XLSX" in body["error"]["message"]


def test_disguised_file_returns_400(make_client):
    response = upload(make_client(), "falso.pdf", b"no soy un pdf", PDF_MIME)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_file"


def test_empty_file_returns_400(make_client):
    response = upload(make_client(), "vacio.docx", b"")
    assert response.status_code == 400


def test_file_too_large_returns_413(make_client):
    client = make_client(max_file_size_mb=0.001)
    response = upload(client, "grande.pdf", b"%PDF-1.7\n" + b"0" * 2048, PDF_MIME)
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "file_too_large"


def test_document_without_items_returns_422(make_client):
    content = pdf_bytes(["Informe trimestral", "Las ventas crecieron durante el periodo."])
    response = upload(make_client(), "informe.pdf", content, PDF_MIME)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "no_items_detected"


def test_llm_reporting_no_items_returns_422(make_client):
    client = make_client(FakeLLMClient({"titulo": "Informe", "idioma": "es", "items": []}))
    response = upload(client, "informe.pdf", pdf_bytes(["Informe trimestral"]), PDF_MIME)
    assert response.status_code == 422


def test_missing_file_field_returns_422(make_client):
    response = make_client().post(ENDPOINT)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_document_too_long_returns_413(make_client):
    client = make_client(max_text_chars=20)
    response = upload(client, "largo.pdf", pdf_bytes(SAMPLE_PDF_LINES), PDF_MIME)
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "document_too_long"


def test_cors_allows_configured_origin_and_exposes_headers(make_client):
    client = make_client(cors_origins="https://front.example.com")
    response = client.options(
        ENDPOINT,
        headers={"Origin": "https://front.example.com", "Access-Control-Request-Method": "POST"},
    )
    assert response.headers["access-control-allow-origin"] == "https://front.example.com"

    llm_client = make_client(FakeLLMClient(LLMRateLimitError("429")), cors_origins="https://front.example.com")
    result = llm_client.post(
        ENDPOINT,
        files={"file": ("q.pdf", pdf_bytes(SAMPLE_PDF_LINES), PDF_MIME)},
        headers={"Origin": "https://front.example.com"},
    )
    assert "X-Extraction-Method" in result.headers["access-control-expose-headers"]


def test_cors_regex_allows_deployment_urls_also_on_errors(make_client):
    # Vercel sirve el frontend también en URLs por despliegue; sin la cabecera CORS el navegador
    # oculta la respuesta (p. ej. un 422) y el frontend solo ve un fallo de red.
    client = make_client(
        cors_origins="https://app.example.com",
        cors_origin_regex=r"https://app-[a-z0-9-]+-team\.example\.com",
    )
    files = {"file": ("vacio.pdf", pdf_bytes([]), PDF_MIME)}
    allowed = "https://app-g86blnqbn-team.example.com"
    response = client.post(ENDPOINT, files=files, headers={"Origin": allowed})
    assert response.status_code == 422
    assert response.headers["access-control-allow-origin"] == allowed

    other = client.post(ENDPOINT, files=files, headers={"Origin": "https://evil.example.com"})
    assert "access-control-allow-origin" not in other.headers
