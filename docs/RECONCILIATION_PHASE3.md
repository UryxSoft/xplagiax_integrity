# Reconciliación de la auditoría de la Fase 1

- **Fecha:** 2026-11-13
- **Entrada:** `docs/AUDIT_PHASE1.md` (commit auditado `cbd7c00`).
- **Regla:** un hallazgo solo figura como "Corregido" si hay una prueba que falla sin la corrección.

## 1. Clasificación y estado

| ID | Hallazgo | Decisión | Estado | Prueba |
|---|---|---|---|---|
| C1 | Credenciales en el historial | Aceptada | **Abierto — solo puede hacerlo el propietario** | — |
| A1 | Enlaces entre organizaciones (`api_requests`, `evidence`) | Aceptada | Corregido | `test_audit_regressions.py::test_a1_*` |
| A2 | Certificados sin integridad | Aceptada parcialmente | Corregido en la BD; ver §2 | `test_a2_*` |
| A3 | Parámetros SQL en logs | Aceptada | Corregido (`hide_parameters=True`) | `test_a3_*` |
| A4 | Clave de plataforma = acceso total | Aceptada | **Pendiente de decisión** (§3) | — |
| M1 | Etapa de otra evaluación | Aceptada | Corregido | `test_m1_*` |
| M2 | Estados e inmutabilidad sin aplicar | Aceptada | Corregido en el ORM; ver §2 | `test_m2_*` |
| M3 | Configuración que falla en abierto | Aceptada | Corregido: `XI_ENV` es obligatoria | `test_config.py::test_missing_environment_name_fails_closed` |
| M4 | Divergencia de intercalación | Aceptada | Corregido: `utf8mb4_bin` en todas las tablas | `test_m4_*` (SQLite y MySQL) |
| M5 | Filtro de lectura por organización opcional | Aceptada | Pendiente: se impone al crear los repositorios de la ingestión | — |
| M6 | Diseño de la cola incompleto | Aceptada | Parcial: `not_before`, estado `cancelled`, `UNIQUE(evaluation_id, sequence)` y regla de orden en ADR-0005. El worker no existe | — |
| M7 | Sin tiempos límite de E/S en la BD | Aceptada | Corregido: `XI_DB_IO_TIMEOUT_S` (30 s). El proxy inverso es tarea de despliegue | — |
| M8 | Pruebas débiles, sin CI | Aceptada | Corregido: test de índices real, test de imports relativos, reglas para `security` y `application`, CI con MySQL 8.4 y build de la imagen | `.github/workflows/ci.yml` |
| M9 | Reproducibilidad sobreafirmada | Aceptada | Corregido en `DATA_MODEL.md` §4 | — |
| M10 | Auditoría parcial | Aceptada parcialmente | Parcial: el alta de organizaciones y usuarios ya se audita. Los fallos de autenticación siguen solo en el log | `test_tenant_provisioning.py` |
| L1 | README desactualizado | Aceptada | Corregido | — |
| L2 | Numeración del roadmap | Aceptada | Corregido: Etapas 1–8 | — |
| L3 | Ruta relativa en `alembic.ini` | Aceptada | Corregido (`%(here)s`), comprobado desde otro directorio | — |
| L4 | La clave de API sale junto a los logs | Aceptada | Pendiente (bajo) | — |
| L5 | Índice redundante; ids en utf8mb4 | Aceptada parcialmente | Índice eliminado. Pasar ids a ASCII queda pendiente: sin mediciones no se justifica | — |
| L6 | Redacción de `x-api-key`; entorno en `/version` | Aceptada | Corregido | `test_health.py` |
| L7 | 16 MiB sin medir | Aceptada | Pendiente: se mide al implementar la ingestión | — |

## 2. Lo que la corrección no cubre

- **A2:** la base de datos garantiza ahora que el informe, la versión y el hash de un certificado pertenecen a la evaluación certificada. **No** puede garantizar que la evaluación esté `completed`: eso lo debe comprobar el caso de uso de emisión, que aún no existe. Los criterios se guardan como hash (`criteria_sha256`) de la definición congelada en `evaluations.config_snapshot`; no hay todavía una tabla de perfiles de criterios.
- **M2:** las reglas viven en el ORM. Un `UPDATE` de SQL directo las salta. Mitigación: el usuario de BD de la aplicación no debe usarse para acceso manual (`SECURITY.md` §5).
- **Migración:** se reescribió `0001` en lugar de añadir `0002`, porque ninguna base de datos había sido migrada todavía. **A partir de ahora, todo cambio de esquema va en una migración nueva.**

## 3. Decisiones pendientes del propietario

1. **C1:** rotar las credenciales. Además, el repositorio `xplagiax_integrity` figura como **público** en GitHub, lo que agrava la exposición.
2. **A4:** ¿la plataforma firmará un token corto por petición con el usuario y la organización, o se acepta el riesgo con red privada y rotación de claves?
3. **Certificados duplicados:** la plataforma ya emite certificados de integridad académica. Ver `docs/INTEGRATION_XPLAGIAX.md` §4.
4. **Valkey o Redis** para el rate limiting.
5. **Orden de productos** (Paper → Dissertation → Patent, recomendado).

## 4. Criterios de aprobación de la Fase 1

| Criterio | Estado |
|---|---|
| C1 cerrado | ❌ Depende del propietario |
| A1, A2, A3, M1 y M3 corregidos con pruebas | ✅ |
| Batería en verde en MySQL 8 dentro de CI | Ver el workflow `CI` en GitHub. La primera ejecución destapó que faltaba `cryptography` para autenticarse en MySQL 8; se añadió |
| Documentación sin las afirmaciones falsas señaladas | ✅ |
