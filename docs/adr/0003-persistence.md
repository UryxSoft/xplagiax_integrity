# ADR-0003 — SQLAlchemy 2.0 directo + Alembic, aislamiento por organización en la BD

- Estado: Propuesto
- Fecha: 2026-11-13

## Decisión
- SQLAlchemy 2.0 sin Flask-SQLAlchemy: los workers y el CLI usan los mismos modelos sin contexto de Flask.
- Alembic solo en CLI y tests. La API comprueba la versión de esquema con una constante (−10 MB de RSS por worker, medido).
- FKs compuestas `(x_id, organization_id)` en todas las relaciones entre tablas de una organización.
- Enums como VARCHAR validados en Python, sin CHECK.
- PyMySQL (Python puro). Se pasaría a mysqlclient si el profiling muestra que el driver es un cuello de botella.

## Consecuencias
- (+) Una consulta sin filtrar por organización aún puede *leer* de más (por eso existe `scoped_select` y se revisa en code review). Las escrituras no pueden enlazar filas de organizaciones distintas en ninguna relación entre tablas de organización. La versión inicial dejaba dos enlaces sin cubrir (`api_requests` → `evaluations` y `evidence` → `api_requests`); la auditoría los detectó y se corrigieron.
- Intercalación `utf8mb4_bin` en todas las tablas, para que las comparaciones se comporten igual en MySQL, MariaDB y SQLite.
- (−) Cada tabla padre necesita un índice único extra `(id, organization_id)`. Coste pequeño.
