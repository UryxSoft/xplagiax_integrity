# Changelog

## [0.3.0] — 2026-11-13 — Etapa 2: ingestión de documentos

### Añadido
- `POST /api/v1/documents`, `POST /api/v1/documents/{id}/versions`, `GET /api/v1/documents/{id}` y `DELETE /api/v1/documents/{id}` (purga).
- Validador del documento de entrada `xplagiax.document/v1`, que devuelve todos los problemas a la vez.
- Idempotencia por organización con `Idempotency-Key`, correcta con peticiones simultáneas en InnoDB.
- Tabla `document_contents`: texto y párrafos comprimidos, con verificación de integridad al leer.
- `TenantScope`: repositorio con filtro de organización obligatorio (cierra el hallazgo M5 de la auditoría para los documentos).
- Visibilidad de documentos por rol (`member`, `reviewer`, `org_admin`).
- Migración `0002`, con relleno de las columnas nuevas para tablas que ya tengan filas.

### Corregido
- En InnoDB, la relectura tras una clave duplicada no veía la fila ganadora (instantánea `REPEATABLE READ`) y, con `FOR UPDATE`, los perdedores se bloqueaban entre sí. Ahora se relee con bloqueo compartido. Afectaba también al alta de organizaciones y usuarios.
- Un `errorhandler` que relanzaba excepciones no producía la respuesta de error correcta.

### Cambiado
- Tope del cuerpo de las peticiones: de 16 a 12 MiB, alineado con el límite de 5 millones de caracteres (mediciones en `docs/PERFORMANCE.md` §1.2).
- `document_ingestion` pasa a `baseline` en `/api/v1/version`.

### Añadido (normalización)
- `integrity/domain/normalization.py`: normalización determinista y neutra respecto al idioma, con mapa exacto de offsets al texto original. 0,41 s y 31 MB de pico para 300.000 palabras (`docs/PERFORMANCE.md` §1.3).

## [0.1.0] — 2026-11-13 — Fase 1: fundación

### Añadido
- App factory de Flask, configuración desde variables de entorno con validación que rechaza configuraciones inseguras en producción.
- Logging JSON (stdlib) con correlation id y redacción de valores sensibles; errores centralizados con un formato único.
- `GET /api/v1/health/live`, `/health/ready` (BD + versión de esquema), `/version` (inventario honesto de motores), `/auth/context`.
- Autenticación de clientes de servicio (HMAC-SHA256 con pepper), contexto de organización y usuario, clientes de plataforma y de organización.
- Modelo de datos de 17 tablas con FKs compuestas por organización; migración Alembic `0001`.
- CLI: `create-org`, `create-user`, `create-client`, `revoke-client`, con eventos de auditoría.
- 89 pruebas en SQLite + 3 de integración opcionales con MySQL (verdes en MariaDB 10.11).
- Documentación: auditoría inicial, arquitectura, modelo de datos, contratos, fuentes, seguridad, rendimiento, validación científica, roadmap y ADRs 0001–0005.
- Dockerfile y docker-compose (escritos, sin construir en esta sesión).

### Seguridad
- Detectadas credenciales reales en `xplagiax_pantents_api_keys.txt`. No se han copiado a ningún sitio. Hay que rotarlas (docs/INITIAL_AUDIT.md §2).

## [0.2.0] — 2026-11-13 — Correcciones de la auditoría e integración con la plataforma

### Corregido (docs/AUDIT_PHASE1.md)
- **A1:** `api_requests` y `evidence` ya no pueden enlazar filas de otra organización.
- **A2:** el informe, la versión y el hash de un certificado deben ser los de la evaluación certificada.
- **A3:** los errores de base de datos ya no escriben los parámetros SQL en los logs.
- **M1:** la etapa de un hallazgo o resultado debe ser de su misma evaluación.
- **M2:** el estado de una evaluación sigue la máquina de estados; las versiones de documento guardadas son inmutables (en el ORM).
- **M3:** `XI_ENV` es obligatoria; ya no hay arranque silencioso en modo desarrollo.
- **M4:** intercalación `utf8mb4_bin`; las referencias distinguen mayúsculas en todos los motores.
- **M7:** tiempo límite de lectura y escritura en la base de datos.
- **M8:** pruebas vacías corregidas; CI con MySQL 8.4 y build de la imagen.
- L1, L2, L3, L5 (índice) y L6.

### Añadido
- Dependencia `cryptography`: PyMySQL la necesita para autenticarse en MySQL 8. Lo detectó la primera ejecución del CI.
- `PUT /api/v1/organizations/{ref}` y `PUT /api/v1/organizations/{ref}/users/{ref}` para que la plataforma dé de alta organizaciones y usuarios.
- Capa `application/` y convenciones compartidas con la plataforma (`text_sha256`, organización personal `user:<id>`).
- `document_versions.word_count`, `evaluations.upstream_ref`, `evaluation_stages.not_before`, `certificates.document_version_id` y `criteria_sha256`.
- `docs/RECONCILIATION_PHASE3.md` y `docs/INTEGRATION_XPLAGIAX.md`.

### Cambiado
- La migración `0001` se reescribió (ninguna base de datos se había migrado). Desde ahora, cada cambio de esquema va en una migración nueva.
- El borrador de extracción v0 se sustituyó por la propuesta v1, basada en la extracción real de appcli2.
- `/version` ya no expone el entorno.
