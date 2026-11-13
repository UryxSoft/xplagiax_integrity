# Contratos de API

Prefijo: `/api/v1`. JSON. Todos los errores usan este formato:

```json
{"error": {"code": "forbidden", "message": "...", "correlation_id": "..."}}
```

Cabeceras transversales:
- `X-Request-ID` (opcional, `[A-Za-z0-9._-]{8,64}`): se devuelve en la respuesta; si no cumple el patrón, se reemplaza.
- `Authorization: Bearer xik_<prefix>_<secret>`: credencial de servicio.
- `X-Integrity-Org` / `X-Integrity-User`: ids externos de appcli2 (`[A-Za-z0-9._:-]{1,64}`). Solo los acepta un cliente de servicio autenticado.

## 1. Endpoints implementados

| Método | Ruta | Auth | Respuestas |
|---|---|---|---|
| GET | `/health/live` | no | `200 {"status":"ok"}`. No consulta dependencias |
| GET | `/health/ready` | no | `200` o `503` con `{"status", "checks": {"database": ok\|schema_missing\|schema_outdated\|unreachable}}` |
| GET | `/version` | no | servicio, versión, `api_version`, entorno, `engines[]` con `maturity` honesta |
| GET | `/auth/context` | sí (organización opcional) | cliente, organización y usuario resueltos. Errores: 401, 403, 422 |

Semántica de errores de auth: `401` = credencial ausente, inválida o revocada. `403` = el cliente no puede actuar para esa organización (también cuando la organización **no existe**, para no revelar cuáles existen) o el usuario no pertenece a ella. `422` = cabecera con formato inválido, o usuario sin organización.

## 2. Endpoints previstos [DISEÑO — no implementados]

| Método | Ruta | Notas |
|---|---|---|
| POST | `/documents` | Cuerpo: JSON de extracción v0. Devuelve `document_id`, `version_id`, `content_sha256`. `Idempotency-Key` obligatoria |
| POST | `/documents/{id}/versions` | Nueva versión (comparación de versiones de tesis) |
| GET / DELETE | `/documents/{id}` | DELETE = purga auditada (DATA_MODEL §5) |
| POST | `/evaluations` | `{product, document_version_id, criteria_profile?}` + `Idempotency-Key` → `202` |
| GET | `/evaluations/{id}` | estado + etapas |
| GET | `/evaluations/{id}/report` | informe JSON (`schema_version`) |
| POST | `/evaluations/{id}/cancel` | |
| GET | `/certificates/verify/{verification_code}` | **público** con rate limit; respuesta mínima: estado, fecha de emisión, prefijo del hash del documento, perfil de criterios. Sin datos personales |

Una sola ruta `POST /evaluations` con `product` en el cuerpo, en vez de tres rutas por producto: el contrato es el mismo y la validación por producto vive en `products/<p>/schemas`.

## 3. JSON de extracción v0 — BORRADOR para acordar con appcli2

> Propuesta del arquitecto. **No hay código que lo use.** Debe compararse con lo que appcli2 produce realmente antes de implementar la Etapa 2.

```json
{
  "schema": "xplagiax.extraction/v0",
  "source": {
    "producer": "xplagiax_appcli2",
    "producer_version": "string",
    "extractor": "string",
    "extractor_version": "string",
    "file_sha256": "hex64",
    "filename": "string (solo informativo; nunca se usa como ruta)",
    "mime_type": "application/pdf",
    "byte_size": 123456,
    "ocr_applied": false
  },
  "document": {
    "title": "string|null",
    "language": "BCP-47|null",
    "page_count": 24,
    "metadata": {"authors": [], "inventors": [], "doi": null, "publication_number": null}
  },
  "blocks": [
    {
      "id": "b-000123",
      "page": 3,
      "order": 123,
      "type": "heading|paragraph|list_item|table|caption|footnote|reference|claim|formula",
      "level": 2,
      "text": "texto original sin normalizar",
      "bbox": [x0, y0, x1, y1],
      "ocr_confidence": null
    }
  ],
  "quality": {
    "pages_failed": [],
    "chars_extracted": 54321,
    "warnings": []
  }
}
```

Reglas previstas:
- `content_sha256` = SHA-256 del JSON canónico de `blocks` (claves ordenadas, UTF-8, sin espacios). Es el ancla de reproducibilidad.
- Los offsets de los hallazgos son `(block_id, char_start, char_end)` sobre `text` **original**; la normalización mantiene un mapa de offsets.
- Si `chars_extracted` es menor que un umbral por producto, `extraction_status = insufficient` y la evaluación se rechaza de forma explícita.
- Límites: 16 MiB por petición (`XI_MAX_REQUEST_BYTES`), número máximo de bloques y tamaño máximo por bloque (a definir con datos reales).
