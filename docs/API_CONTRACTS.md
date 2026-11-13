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
| GET | `/version` | no | servicio, versión, `api_version`, `engines[]` con `maturity` honesta. No expone el entorno |
| GET | `/auth/context` | sí (organización opcional) | cliente, organización y usuario resueltos. Errores: 401, 403, 422 |
| PUT | `/organizations/{ref}` | sí, **solo cliente de plataforma** | Cuerpo `{"name"}`. Idempotente: `201` si la crea, `200` si ya existía. Errores: 401, 403, 422 |
| PUT | `/organizations/{ref}/users/{ref}` | sí, **solo cliente de plataforma** | Cuerpo `{"role"?}` (`member` por defecto). Idempotente; actualiza el rol si cambia. Errores: 401, 403, 404, 422 |

La plataforma no tiene organizaciones: cada usuario usa la referencia `user:<id>` (INTEGRATION_XPLAGIAX §2).

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

## 3. Documento de entrada v1 — PROPUESTA para acordar con appcli2

> Sustituye al borrador v0 (bloques con coordenadas), que no correspondía a lo que la plataforma produce. Esta versión parte de la forma real de la extracción de appcli2 (INTEGRATION_XPLAGIAX §1). **No hay código que la use todavía.**

```json
{
  "schema": "xplagiax.document/v1",
  "source": {
    "producer": "xplagiax_appcli2",
    "producer_version": "string",
    "analysis_ref": "uuid del historial de análisis de la plataforma | null",
    "file_sha256": "hex64 | null",
    "filename": "solo informativo; nunca se usa como ruta",
    "mime_type": "application/pdf"
  },
  "text": "texto completo extraído",
  "paragraphs": [[1, 1, "texto del párrafo"], [1, 2, "…"]],
  "word_count": 5321,
  "language": "en",
  "metadata": {"title": null, "author": null},
  "extraction": {
    "status": "complete | partial | failed",
    "pages_total": 24,
    "pages_with_text": 24,
    "pages_needing_ocr": [],
    "pages_failed": [],
    "ocr": null,
    "format": "pdf"
  }
}
```

Reglas previstas:
- `content_sha256` = `text_sha256(text)`: SHA-256 del texto con los espacios colapsados, la misma definición que usa la plataforma.
- `paragraphs` es opcional. Si llega, cada elemento es `[página, nº de párrafo, texto]` y las ubicaciones de los hallazgos son `(página, párrafo, char_start, char_end)`. Si no llega, las ubicaciones son offsets sobre `text`.
- `extraction.status = failed`, o menos palabras que el umbral del producto → se rechaza de forma explícita (`extraction_status = insufficient`). `partial` se acepta y queda como limitación en el informe.
- Límites: 16 MiB por petición (`XI_MAX_REQUEST_BYTES`); número máximo de párrafos y tamaño por párrafo, a definir con datos reales.
