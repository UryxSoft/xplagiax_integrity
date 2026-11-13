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

| POST | `/documents` | sí, organización obligatoria | Cuerpo: documento v1 (§3). Cabecera `Idempotency-Key` obligatoria. `201` creado, `200` repetición idéntica. Errores: 401, 403, 409 (clave reutilizada con otro contenido), 413, 422 (`invalid_document` con `details`, o `insufficient_content`) |
| POST | `/documents/{id}/versions` | sí | Igual que el anterior; crea la versión siguiente. Errores adicionales: 404, 409 (`concurrent_modification`), 410 (documento borrado) |
| GET | `/documents/{id}` | sí | Metadatos del documento y de sus versiones. **Nunca devuelve el texto** |
| DELETE | `/documents/{id}` | sí | Purga el contenido de todas las versiones. Conserva hashes, metadatos y auditoría. Idempotente |

| POST | `/evaluations` | sí | Cuerpo `{document_version_id, product, criteria_profile?, criteria_version?}` + `Idempotency-Key`. `202` encolada, `200` repetición. Errores: 404 (versión no visible), 409, 410 (documento borrado), 422 |
| GET | `/evaluations/{id}` | sí | Estado, etapas (estado, intentos, error) y resultado de cada etapa terminada (`payload`, `payload_sha256`, `limitations`) |
| GET | `/evaluations/{id}/report` | sí | Informe JSON (§4). `409` si la evaluación no ha terminado; `500 report_mismatch` si los datos guardados ya no reproducen el informe registrado |
| POST | `/evaluations/{id}/cancel` | sí | Idempotente. Cancela las etapas pendientes; la que esté en curso termina y su resultado se descarta |

La plataforma no tiene organizaciones: cada usuario usa la referencia `user:<id>` (INTEGRATION_XPLAGIAX §2).

**Etapas disponibles hoy** (`integrity/domain/workflows.py`). Solo figuran las que tienen un motor real y probado:

| Producto | Etapas |
|---|---|
| `research_paper`, `dissertation` | `content_check` (el texto coincide con el hash de la ingesta; resumen de calidad) → `doi_detection` (opcional: DOI escritos y su ubicación; **sin verificar**) → `citation_consistency` (opcional: citas sin referencia y referencias no citadas) |
| `patent_integrity` | `content_check` |

Estados: la evaluación pasa por `queued → processing → completed | partially_completed | failed | cancelled`. `partially_completed` significa que falló una etapa opcional; un fallo de una etapa obligatoria da `failed` y marca las siguientes como `skipped`.

**Visibilidad de documentos** según el usuario afirmado en `X-Integrity-User`:

| Usuario | Leer | Añadir versión | Borrar |
|---|---|---|---|
| Ninguno (la plataforma actúa por la organización) | todos | todos | todos |
| `member` | los suyos | los suyos | los suyos |
| `reviewer` | todos los de la organización | no | no |
| `org_admin` | todos | todos | todos |

Un documento que el usuario no puede leer responde `404`, no `403`, para no revelar que existe.

**Idempotencia:** `Idempotency-Key` es `[A-Za-z0-9._:-]{8,128}` y es única por organización. Repetir la misma clave con el mismo contenido devuelve la versión ya creada; con otro contenido devuelve `409`. Ocho peticiones simultáneas con la misma clave crean exactamente una versión (probado en MariaDB).

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

## 3. Documento de entrada v1 — IMPLEMENTADO, pendiente de confirmar con appcli2

> Sustituye al borrador v0 (bloques con coordenadas), que no correspondía a lo que la plataforma produce. Esta versión parte de la forma real de la extracción de appcli2 (INTEGRATION_XPLAGIAX §1). Validador: `integrity/domain/ingestion_contract.py`.

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
- Todos los problemas de formato se devuelven juntos en `error.details` (hasta 50).
- Límites implementados (`ContractLimits`): texto ≤ 5.000.000 caracteres; ≤ 50.000 párrafos de ≤ 50.000 caracteres; ≤ 10.000 páginas; mínimo 10 palabras (el mismo mínimo que aplica appcli2). Cuerpo ≤ 12 MiB (`XI_MAX_REQUEST_BYTES`).
- `extraction.status = partial`, idioma no detectado o un `word_count` declarado distinto del recibido **no se rechazan**: se guardan como limitaciones de la versión para que aparezcan en el informe.
- `source.filename` se guarda como dato y nunca se usa como ruta.

**Pregunta abierta para appcli2:** el texto viaja dos veces (en `text` y dentro de `paragraphs`). Si appcli2 siempre envía párrafos, `text` podría derivarse de ellos y el cuerpo se reduciría casi a la mitad.

## 4. Informe JSON (`schema_version` 1)

Se construye **solo con lo guardado** (`integrity/application/reports.py`); no recalcula nada.

| Campo | Contenido |
|---|---|
| `evaluation`, `document` | Identificadores, estado, `config_sha256`, criterios, `content_sha256` y `file_sha256` del documento evaluado |
| `stages[]` | Por etapa: estado, motor (nombre, versión, hash de configuración), `result_sha256` y resumen |
| `sources_consulted[]` | Fuente, operación, resultado y número de llamadas. Incluye las bloqueadas por política |
| `findings[]` | Categoría, `nature` y su explicación, severidad, método, ubicación, limitaciones, recomendación y evidencias (fragmento y su SHA-256) |
| `limitations[]` | Las de la ingesta y las de cada etapa, más las etapas que no terminaron |
| `disclaimer[]` | Límites del producto, y que la ausencia de hallazgos no significa originalidad |
| `report` | `id`, `content_sha256` y la fecha de primera generación |

**Reproducibilidad:** `content_sha256` se calcula sobre una forma canónica en la que cada fragmento se sustituye por su SHA-256. Regenerar el informe da el mismo hash, también después de purgar el documento. Si los datos guardados cambian (por ejemplo, se edita un hallazgo), el servicio rechaza el informe en lugar de devolver uno distinto.
