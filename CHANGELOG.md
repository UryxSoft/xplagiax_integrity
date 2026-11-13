# Changelog

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
