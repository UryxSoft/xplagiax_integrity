# Auditoría independiente de la Fase 1 — XplagiaX Integrity

- **Fecha:** 2026-11-13
- **Commit auditado:** `cbd7c00`
- **Modo:** solo lectura. La auditoría no modificó código, migraciones ni configuración.
- **Veredicto:** **la Fase 1 no queda aprobada todavía.** La base es sólida y los fallos son acotados, pero hay un incidente crítico abierto y cuatro defectos altos que conviene cerrar antes de escribir la ingestión.

## Método y límites

- Los hallazgos marcados como **confirmados** se reprodujeron con scripts fuera del repositorio, contra SQLite y MariaDB 10.11.14 (intercalación `utf8mb4_general_ci`).
- **MySQL 8 no estaba disponible.** Todo lo relativo a ese motor queda sin verificar.
- **Independencia limitada:** la auditoría se hizo en la misma sesión en la que se construyó la Fase 1. Por eso se apoya en pruebas ejecutadas y no en la documentación.
- La rama ya estaba subida a GitHub cuando se hizo la auditoría. El archivo de credenciales ya estaba en `origin/main` desde antes, así que ese push no empeoró la exposición.

## 1. Resumen ejecutivo

- **Lo que funciona:** la cadena principal de aislamiento (documento → versión → evaluación → etapa → hallazgo → evidencia) rechaza enlaces entre organizaciones en ambos motores. Las claves de API se guardan como HMAC, los errores 500 no filtran detalles en la respuesta y el modelo coincide con la migración en MariaDB.
- **Lo que falla:** el aislamiento tiene dos huecos reales, los certificados no tienen integridad en la base de datos, los logs filtran datos de documentos y la configuración arranca en modo inseguro si falta una variable.
- **Lo que no existe:** servicios, repositorios, interfaces de motores y workers. No se pueden aprobar ni rechazar; solo hay diseño.

## 2. Hallazgos críticos

### C1 — Credenciales reales en el historial de Git
- **Ubicación:** `xplagiax_pantents_api_keys.txt`, commit `33d4af1`, presente en `main` y en la rama de trabajo.
- **Impacto:** cualquier persona o integración con acceso de lectura tiene las credenciales de EPO OPS, la contraseña de la cuenta y la clave de IP Australia.
- **Recomendación:** rotarlas primero, después borrar el archivo y por último limpiar el historial. El orden importa: limpiar el historial no anula un secreto ya filtrado.

## 3. Hallazgos altos

### A1 — Dos enlaces entre organizaciones se aceptan (confirmado en SQLite y MariaDB)
- **Ubicación:** `integrity/infrastructure/db/models/sources.py` (`ApiRequest.evaluation_id`) y `integrity/infrastructure/db/models/evaluations.py` (`Evidence.api_request_id`). Ambas son claves foráneas simples.
- **Evidencia:** un `api_request` de la organización A apuntando a una evaluación de B se guardó sin error. Una evidencia de A apuntando a un `api_request` de B, también.
- **Impacto:** un error de aplicación podría mostrar en el informe de A qué consultó B. Además, `docs/adr/0003-persistence.md` afirma que "ninguna escritura puede mezclar organizaciones", y eso es falso. `docs/DATA_MODEL.md` §3 solo declara pendiente uno de los dos enlaces.
- **Recomendación:** claves compuestas también aquí. Para los health checks sin organización, usar una tabla aparte o una organización de sistema.

### A2 — Los certificados no tienen integridad en la base de datos (confirmado)
- **Ubicación:** `integrity/infrastructure/db/models/outputs.py`, clase `Certificate`.
- **Evidencia:** se guardó un certificado `CERTIFIED` con la evaluación en estado `pending`, con el informe de otra evaluación y con un hash de documento distinto al de la versión evaluada.
- **Impacto:** el certificado es el producto de mayor valor y hoy puede acreditar algo que no ocurrió.
- **Agravante:** `criteria_profile` es un texto libre. No hay tabla que guarde la definición de los criterios, así que no se puede auditar con qué reglas se emitió.
- **Recomendación:** clave compuesta `(report_id, evaluation_id)`, hash derivado de la versión y no copiado, tabla de perfiles de criterios versionados, y emisión solo desde un caso de uso que verifique el estado.

### A3 — Los logs filtran datos de documentos (confirmado)
- **Ubicación:** `integrity/infrastructure/db/session.py` (`build_engine` no usa `hide_parameters=True`) y `integrity/core/errors.py` (`log.exception`).
- **Evidencia:** un error de base de datos no controlado devolvió un 500 limpio, pero el log contenía el título del documento, porque SQLAlchemy incluye los parámetros SQL en el mensaje de la excepción.
- **Impacto:** títulos, fragmentos de evidencia y claves de idempotencia de documentos confidenciales acabarían en los logs. Contradice `docs/SECURITY.md`.
- **Recomendación:** `hide_parameters=True` y un test que lo impida.

### A4 — Una sola clave de plataforma da acceso a todas las organizaciones
- **Ubicación:** `integrity/security/auth.py`, `_resolve_tenant`.
- **Evidencia:** el cliente de plataforma afirma organización y usuario por cabecera, sin prueba firmada. No hay rate limiting, caducidad de claves ni varias claves por cliente.
- **Impacto:** robar la clave de appcli2 equivale a leer todo. `docs/SECURITY.md` §3 lo reconoce, pero no hay mitigación.
- **Recomendación:** decidir antes de la ingestión si appcli2 firmará un token corto por petición. Cambiarlo después obliga a rehacer el contrato.

## 4. Hallazgos medios

| ID | Hallazgo | Ubicación | Estado |
|---|---|---|---|
| M1 | Un hallazgo de la evaluación 1 puede apuntar a una etapa de la evaluación 2 (misma organización). Rompe la trazabilidad del método | `models/evaluations.py`, `Finding` y `EvaluationResult` | Confirmado |
| M2 | Estados e inmutabilidad sin aplicar: una evaluación pasó de `completed` a `pending` y se reescribió el hash de una versión "inmutable" | `domain/evaluation_state.py` no lo usa ningún código | Confirmado |
| M3 | Configuración que falla en abierto: sin `XI_ENV` arranca en `development`, con SQLite y un pepper público. El Dockerfile lo mitiga; un despliegue manual no | `integrity/config.py`, `from_env` | Confirmado |
| M4 | Divergencia entre motores: la cabecera `ORG-A` resuelve la organización `org-a` en MariaDB y da 403 en SQLite. MySQL 8 usa otra intercalación por defecto | `db/base.py`, `TABLE_ARGS` no fija intercalación | Confirmado |
| M5 | El filtro de lectura por organización es opcional: `scoped_select` no tiene ningún uso y nada impide un `session.get()` directo | `db/tenant.py`; no hay capa de repositorios | Inspección |
| M6 | Diseño de la cola incompleto: no impide tomar la etapa 2 antes de que acabe la 1, no hay espera entre reintentos ni estado de cancelación por etapa; `SKIP LOCKED` sin probar | `docs/adr/0005-background-work.md` | Inspección |
| M7 | Sin tiempos límite de lectura en la BD. Con dos workers síncronos y sin proxy inverso, una BD colgada o clientes lentos bloquean el servicio | `db/session.py` (solo `connect_timeout`), `Dockerfile` | Inspección |
| M8 | Pruebas más débiles de lo que aparentan (detalle abajo) | `tests/` | Inspección |
| M9 | Reproducibilidad sobreafirmada: solo se guarda el hash de las respuestas externas. Se detecta que una fuente cambió, no se reproduce el resultado | `docs/DATA_MODEL.md` §4 | Inspección |
| M10 | Auditoría parcial: solo el CLI escribe eventos y se pierden si la transacción falla; "solo inserción" es una convención | `security/audit.py` | Inspección |

Detalle de M8:
- `tests/test_migrations.py:43`: la condición `"id" not in leading` siempre se cumple, así que el test no puede fallar.
- `tests/test_architecture.py:23`: ignora los imports relativos y no tiene reglas para `security`.
- No hay CI. Las pruebas de MySQL son opcionales, MySQL 8 nunca se ejecutó y la imagen Docker nunca se construyó.

## 5. Hallazgos bajos

- **L1.** `README.md` (líneas 137 y 190, y sus equivalentes en español) aún muestra la estructura `app/` y "Redis", contra el paquete `integrity/` y el ADR-0005.
- **L2.** `docs/ROADMAP.md` numera las etapas 0, 1b, 2, 3, 3b…, distinto de las Etapas 1–8 del encargo y de las fases del prompt maestro.
- **L3.** `alembic.ini` usa una ruta relativa: las migraciones solo funcionan desde la raíz del repo (confirmado).
- **L4.** `integrity/cli.py` imprime la clave de API en la misma salida que los logs JSON.
- **L5.** Índice redundante en `users.organization_id`. Los identificadores y hashes usan utf8mb4 en vez de ASCII.
- **L6.** La redacción de logs no cubre `x-api-key`. `/version` expone el entorno sin autenticación.
- **L7.** El límite de 16 MiB por petición no está medido contra el presupuesto de 80 MB por worker.

## 6. Defectos arquitectónicos

- No se encontraron dependencias circulares y la separación de capas existente es correcta.
- Faltan las capas de aplicación, repositorios, interfaces de motores, workers e informes. Están documentadas como diseño, pero no hay código (ver M5).
- No hay una política de transacciones para la API: `db_session()` no define quién confirma ni quién revierte.
- `core` importa Flask, así que los motores futuros lo arrastrarán.
- **Python frente a Rust:** no existe todavía ningún componente que consuma CPU, así que no hay nada que medir. Se mantiene Python; Rust se valoraría con benchmarks de motores reales.

## 7. Riesgos de seguridad

Los riesgos son C1, A1, A3, A4, M3 y M5. Vías concretas para acceder hoy a datos de otra organización:
- la clave de plataforma (A4);
- los dos enlaces de A1;
- cualquier consulta futura que no use `scoped_select` (M5).

## 8. Riesgos de base de datos

- Los defectos son A1, A2, M1, M2 y M4.
- La migración en MySQL no es transaccional: si falla a medias deja un esquema parcial que hay que limpiar a mano.
- No hay cascadas, lo cual es correcto, pero la purga por retención sigue sin diseñarse en detalle.

## 9. Riesgos de rendimiento

- **Medido en una sola ejecución:** 57,5 MB por worker, 0,32 s de arranque y latencias sin red ni concurrencia.
- **Estimado, sin medir:** los presupuestos de `docs/PERFORMANCE.md` §3.
- **Sin medir:** percentiles bajo carga, uso del pool de conexiones y coste del sondeo de la cola.
- Valkey no se usa. Su única justificación actual es el rate limiting, que es justo lo que falta en A4.

## 10. Contratos de integración

- **Implementados:** `/health/live`, `/health/ready`, `/version` y `/auth/context`.
- **Propuestas:** todo lo demás de `docs/API_CONTRACTS.md`, incluido el JSON de extracción v0.
- **Servicios hermanos:** no hay ningún contrato de appcli2, beyond_xota, finderx ni scitrace en el repositorio. Esa integración no se puede evaluar.

## 11. Recomendaciones priorizadas

1. Rotar las credenciales y limpiar el historial (C1).
2. Corregir A3 y M3; son cambios de pocas líneas.
3. Añadir una migración `0002` con las claves compuestas de A1, A2 y M1 y una intercalación explícita (M4).
4. Montar CI con MySQL 8 real y arreglar las pruebas de M8.
5. Decidir el modelo de confianza con appcli2 (A4) e introducir rate limiting.
6. Corregir la documentación (ADR-0003, DATA_MODEL §4, README, numeración del roadmap).

## 12. Criterios de aprobación y bloqueos

**Para aprobar la Fase 1:**
- C1 cerrado.
- A1, A2, A3, M1 y M3 corregidos, cada uno con un test que falle sin la corrección.
- Toda la batería en verde en MySQL 8, dentro de CI.
- La documentación sin las afirmaciones falsas señaladas.

**Bloqueos antes de empezar la implementación de la ingestión:**
- El contrato real de appcli2.
- La decisión sobre A4.
- La política de transacciones y la capa de repositorios (M5).
- El diseño de la cola completado (M6).
