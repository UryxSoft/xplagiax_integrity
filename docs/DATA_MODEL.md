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
| Motor | InnoDB, utf8mb4 | FKs, transacciones, Unicode completo |

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
| `document_versions` | Instantánea **inmutable** de lo que se analizó: `content_sha256`, `file_sha256`, `storage_ref`, estado y motor de extracción | UQ `(document_id, version_number)`; IX `(organization_id, content_sha256)` |
| `engine_versions` | Registro de `(motor, versión, sha256 de config)` | UQ de las tres columnas |
| `evaluations` | Una ejecución de un producto sobre una versión. `config_snapshot` + `config_sha256` congelados | UQ `(organization_id, idempotency_key)`; IX `(organization_id, status, created_at)` |
| `evaluation_stages` | Traza por etapa **y** unidad de trabajo de los workers (lease, intentos) | UQ `(evaluation_id, stage_name)`; IX `(status, lease_expires_at)` |
| `evaluation_results` | Salida agregada de una etapa, con hash y limitaciones | UQ `stage_id` |
| `findings` | Hallazgo: `category`, **`nature`**, `severity`, `method`, `confidence` + `confidence_calibrated`, `location`, `limitations` | CHECK 0≤confidence≤1; CHECK confidence ⇒ hay flag de calibración |
| `evidence` | Lo que respalda un hallazgo: fragmento (acotado y con hash), registro externo, métrica o resultado de una API | FK de organización → findings, document_versions |
| `external_sources` | Registro de proveedores con **permisos tri-estado** (`NULL` = desconocido = no permitido) | UQ `code`; `enabled` es false por defecto |
| `api_requests` | Cada llamada saliente, **incluidos los rechazos por política y los aciertos de caché**. Se guarda la huella de la consulta, no la consulta | IX `(organization_id, requested_at)`, `(external_source_id, request_fingerprint)` |
| `reports` | Informe generado: formato, versión de esquema, sha256, `storage_ref` | IX `(evaluation_id, generated_at)` |
| `certificates` | Estado, `verification_code` público y aleatorio, hash del documento, perfil y versión de criterios, firma (pendiente) | UQ `verification_code`, UQ `evaluation_id`; CHECK certified ⇒ issued_at y report; CHECK revoked ⇒ revoked_at |
| `audit_events` | Registro de solo inserción; sin contenido | IX `(organization_id, occurred_at)`, `(target_type, target_id)` |

## 3. Aislamiento por organización

1. Toda tabla de una organización tiene `organization_id NOT NULL` (salvo `api_requests` y `audit_events`, donde es opcional para eventos de sistema o de salud).
2. Cada tabla padre declara `UNIQUE (id, organization_id)`. Cada FK hija es compuesta: `(parent_id, organization_id) → parent(id, organization_id)`. **Una fila no puede apuntar a un padre de otra organización.** Probado (`test_tenant_isolation.py`, `test_mysql_integration.py`).
3. Todo el acceso a datos de una organización pasa por `scoped_select(Model, org_id)`, que falla si el id está vacío o si el modelo es global.
4. El `organization_id` sale **solo** de `TenantContext` (la credencial autenticada), nunca del cuerpo de la petición.
5. **La deduplicación es solo dentro de cada organización.** Un índice de hash entre organizaciones permitiría averiguar si otra organización ya tiene un documento concreto.

Pendiente, a decidir en la Fase 2: claves foráneas compuestas hacia `api_requests` y `external_sources` desde `evidence` (hoy son simples porque esas filas pueden no tener organización).

## 4. Reproducibilidad

Un hallazgo queda determinado por: `document_versions.content_sha256` + `evaluations.config_sha256` + `engine_versions(engine, version, config_sha256)` + las filas de `api_requests` con `response_sha256`. Reevaluar con las mismas cuatro cosas debe dar los mismos hallazgos; si el resultado no es determinista (servicios externos, modelos), debe declararlo en `limitations`.

## 5. Retención y borrado [DISEÑO]

- Purgar = borrar el blob (`storage_ref`) y `evidence.excerpt_text`, y marcar `documents.purged_at`. **Se conservan** los hashes, los hallazgos sin fragmentos y la auditoría, para que un certificado emitido pueda verificarse sin guardar el contenido.
- No hay `ON DELETE CASCADE`: el borrado es una operación explícita y auditada (Etapa 2).
- Retención por defecto de la plataforma: a definir con negocio y legal. `organizations.retention_days` la puede reducir.
