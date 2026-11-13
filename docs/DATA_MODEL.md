# Modelo de datos

Fuente de verdad: `integrity/infrastructure/db/models/` + `integrity/migrations/versions/20261113_0001_initial_schema.py`.
`tests/test_migrations.py` falla si los modelos y la migración no coinciden (SQLite). `tests/test_mysql_integration.py` hace la misma comprobación en MySQL/MariaDB.

## 1. Convenciones

| Aspecto | Decisión | Motivo |
|---|---|---|
| PK | `CHAR(36)` UUIDv7 | Ordenado por tiempo → buena localidad en el índice clúster de InnoDB; no enumerable (ADR-0004) |
| Tiempo | `DATETIME(6)` en UTC sin zona en la BD; *aware* en Python | MySQL no guarda zona horaria; se rechazan datetimes *naive* al escribir |
| Enums | `VARCHAR(32)`, validados en Python | Ampliar un vocabulario no obliga a migrar un CHECK |
| Hashes | `CHAR(64)` SHA-256 en hex | Anclas de reproducibilidad |
| JSON | `JSON` de MySQL | Ubicaciones, configuración congelada, limitaciones |
| Nombres | Convención fija de constraints; todos ≤ 64 caracteres (probado) | Exigencia de MySQL y migraciones estables |
| Motor | InnoDB, utf8mb4, intercalación `utf8mb4_bin` | FKs, transacciones, Unicode completo. Las comparaciones distinguen mayúsculas en todos los motores, igual que en SQLite |

## 2. Entidades

```text
organizations ─┬─ users
               ├─ service_clients (scope=organization)        service_clients (scope=platform, sin org)
               ├─ projects ── documents ── document_versions
               │                                 │
               │                       evaluations ─┬─ evaluation_stages ── evaluation_results
               │                                    │          │
               │                                    │       findings ── evidence ──► external_sources
               │                                    │                       └──────► api_requests
               │                                    ├─ reports
               │                                    └─ certificates ─► reports
               └─ audit_events
Global (sin organización): engine_versions, external_sources
```

| Tabla | Propósito | Claves e índices principales |
|---|---|---|
| `organizations` | Organización; espejo del id de appcli2 (`external_ref`) | UQ `external_ref` |
| `users` | Espejo de un usuario de appcli2 dentro de una organización. **Sin credenciales** | UQ `(organization_id, external_ref)`, UQ `(id, organization_id)` |
| `service_clients` | Credencial de máquina; solo se guarda el HMAC | UQ `key_prefix`; CHECK scope↔org |
| `projects` | Agrupación opcional | FK de organización → users |
| `documents` | Documento lógico; `retention_until`, `purged_at` | IX `(organization_id, created_at)`, IX `retention_until` |
| `document_versions` | Instantánea **inmutable** de lo que se analizó: `content_sha256`, `file_sha256`, `idempotency_key`, `upstream_ref`, productor, estado de extracción y limitaciones recibidas | UQ `(document_id, version_number)`; IX `(organization_id, content_sha256)` |
| `document_contents` | Texto y párrafos de una versión, comprimidos (`zlib+json/v1`) con el SHA-256 del blob. Tabla aparte para que las consultas de metadatos no carguen texto y la purga borre solo esto | PK `version_id`; FK de organización → document_versions |
| `engine_versions` | Registro de `(motor, versión, sha256 de config)` | UQ de las tres columnas |
| `evaluations` | Una ejecución de un producto sobre una versión. `config_snapshot` + `config_sha256` congelados | UQ `(organization_id, idempotency_key)`; IX `(organization_id, status, created_at)` |
| `evaluation_stages` | Traza por etapa **y** unidad de trabajo de los workers (lease, intentos, `not_before`) | UQ `(evaluation_id, stage_name)`, UQ `(evaluation_id, sequence)`; IX `(status, not_before, lease_expires_at)` |
| `evaluation_results` | Salida agregada de una etapa, con hash y limitaciones | UQ `stage_id` |
| `findings` | Hallazgo: `category`, **`nature`**, `severity`, `method`, `confidence` + `confidence_calibrated`, `location`, `limitations` | CHECK 0≤confidence≤1; CHECK confidence ⇒ hay flag de calibración |
| `evidence` | Lo que respalda un hallazgo: fragmento (acotado y con hash), registro externo, métrica o resultado de una API | FK de organización → findings, document_versions |
| `external_sources` | Registro de proveedores con **permisos tri-estado** (`NULL` = desconocido = no permitido) | UQ `code`; `enabled` es false por defecto |
| `api_requests` | Cada llamada saliente, **incluidos los rechazos por política y los aciertos de caché**. Se guarda la huella de la consulta, no la consulta | IX `(organization_id, requested_at)`, `(external_source_id, request_fingerprint)` |
| `reports` | Informe generado: formato, versión de esquema, sha256, `storage_ref` | IX `(evaluation_id, generated_at)` |
| `certificates` | Estado, `verification_code` público y aleatorio, versión y hash del documento, perfil, versión y `criteria_sha256`, firma (pendiente) | UQ `verification_code`, UQ `evaluation_id`; CHECK certified ⇒ issued_at y report; CHECK revoked ⇒ revoked_at |
| `audit_events` | Registro de solo inserción; sin contenido | IX `(organization_id, occurred_at)`, `(target_type, target_id)` |

## 3. Aislamiento por organización

1. Toda tabla de una organización tiene `organization_id NOT NULL` (salvo `api_requests` y `audit_events`, donde es opcional para eventos de sistema o de salud).
2. Cada tabla padre declara `UNIQUE (id, organization_id)`. Cada FK hija es compuesta: `(parent_id, organization_id) → parent(id, organization_id)`. **Una fila no puede apuntar a un padre de otra organización.** Probado (`test_tenant_isolation.py`, `test_mysql_integration.py`).
3. Todo el acceso a datos de una organización pasa por `scoped_select(Model, org_id)`, que falla si el id está vacío o si el modelo es global.
4. El `organization_id` sale **solo** de `TenantContext` (la credencial autenticada), nunca del cuerpo de la petición.
5. **La deduplicación es solo dentro de cada organización.** Un índice de hash entre organizaciones permitiría averiguar si otra organización ya tiene un documento concreto.

6. **Coherencia dentro de una organización** (tras la auditoría):
   - `findings` y `evaluation_results` referencian `(stage_id, evaluation_id, organization_id)`: la etapa es de esa misma evaluación.
   - `api_requests` referencia `(evaluation_id, organization_id)` y exige organización si hay evaluación. `evidence` referencia `(api_request_id, organization_id)`. Las llamadas de sistema (sin organización) no pueden citarse como evidencia.
   - `certificates` referencia `(evaluation_id, document_version_id, organization_id)`, `(report_id, evaluation_id, organization_id)` y `(document_version_id, organization_id, document_content_sha256)`: el informe, la versión y el hash son los de la evaluación certificada.
7. **Reglas en el ORM:** `evaluations.status` solo avanza según la máquina de estados del dominio, y la identidad y los hashes de `document_versions` no se pueden cambiar una vez guardados. Un `UPDATE` de SQL directo las salta.

`external_sources` y `engine_versions` son globales y se referencian con FK simple.

## 4. Reproducibilidad

Un hallazgo queda **atribuido** a: `document_versions.content_sha256` + `evaluations.config_sha256` + `engine_versions(engine, version, config_sha256)` + las filas de `api_requests`.

Qué garantiza esto y qué no:
- Los motores deterministas (sin llamadas externas) deben dar el mismo resultado con las mismas tres primeras entradas. Eso se podrá comprobar con pruebas.
- Las respuestas de proveedores externos **no se guardan**; solo su hash (`response_sha256`). Se puede detectar que una fuente respondió distinto en una reevaluación, pero **no reproducir** el resultado original. Los hallazgos que dependan de fuentes externas o de modelos deben declararlo en `limitations`.

## 5. Retención y borrado [PARCIAL]

- Purgar = borrar las filas de `document_contents` y los `evidence.excerpt_text` del documento (sus hashes se conservan), poner `documents.title` a nulo y marcar `documents.purged_at`. **Implementado** en `DELETE /documents/{id}`. **Se conservan** los hashes, los hallazgos sin fragmentos y la auditoría, para que un certificado emitido pueda verificarse sin guardar el contenido.
- No hay `ON DELETE CASCADE`: el borrado es una operación explícita y auditada (Etapa 2).
- `documents.retention_until` se calcula al ingerir a partir de `organizations.retention_days`. **Falta** el proceso periódico que purga los vencidos.
- Retención por defecto de la plataforma: a definir con negocio y legal.
