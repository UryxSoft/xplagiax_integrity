# ADR-0005 — Trabajo en segundo plano: etapas con lease en MySQL; Valkey solo para rate limiting y caché

- Estado: **Implementado** (`integrity/workers/runner.py`); comportamiento concurrente probado en MariaDB
- Fecha: 2026-11-13

## Contexto
Hace falta procesar en segundo plano, con estado durable por etapa, reintentos, cancelación y recuperación tras un fallo. El estado tiene que vivir en MySQL de todos modos, por trazabilidad. La especificación pide Redis o Valkey solo cuando aporten una ventaja demostrable.

## Decisión
- `evaluation_stages` **es** la cola. Un worker toma una etapa con un `UPDATE … SET status='running', lease_owner=?, lease_expires_at=? WHERE id=? AND status='pending'` condicional (o `SELECT … FOR UPDATE SKIP LOCKED` en MySQL 8) y renueva el lease mientras trabaja. Un lease caducado vuelve a `pending` si `attempt < max_attempts`.
- **Orden:** un worker solo toma una etapa si no queda ninguna etapa anterior (`sequence` menor) de la misma evaluación sin terminar, y si `not_before` es nulo o ya pasó. `UNIQUE(evaluation_id, sequence)` evita ambigüedades.
- **Reintentos:** al fallar, la etapa vuelve a `pending` con `not_before` = ahora + espera creciente, hasta `max_attempts`.
- **Cancelación:** cancelar una evaluación marca sus etapas pendientes como `cancelled`; la que está en curso termina y no se inicia la siguiente.
- Sin Celery ni RQ: el estado de la cola y el estado de la evaluación viven en un solo sitio y el sistema de colas no cuesta RAM ni mantenimiento.
- Valkey (instancia propia, no el Redis compartido) se introduce para el rate limiting y la caché de respuestas de proveedores, cuando esas funciones existan.

## Consecuencias
- (+) No hay que reconciliar la cola con la BD. La idempotencia sale de `UNIQUE(evaluation_id, stage_name)`.
- (−) Sondear la tabla de etapas: con un intervalo de 1 a 2 s y un índice `(status, lease_expires_at)` la carga es despreciable con el volumen previsto. Se reconsiderará con mediciones.
- Revisar en la Fase 2: el comportamiento de `SKIP LOCKED` en MySQL 8 frente a MariaDB y el riesgo de dejar de detectar trabajos colgados.

## Implementación (2026-11-13)

- `flask --app integrity.app:create_app integrity worker` procesa una etapa cada vez; se escala con más procesos. `SIGTERM` termina la etapa en curso y sale. `--max-stages N` recicla el proceso.
- La toma de etapas es un `UPDATE` condicional (correcto en cualquier motor), precedido en MySQL por `SELECT … FOR UPDATE SKIP LOCKED`.
- El motor se ejecuta **sin transacción abierta**. El resultado solo se guarda si el worker sigue teniendo el lease; un worker que vuelve tras perderlo no sobrescribe nada.
- Lease por defecto de 300 s. **No hay renovación del lease**: una etapa que tarde más se considerará abandonada y otro worker la repetirá. Hará falta renovarlo en cuanto exista un motor lento.
- Reintentos solo para errores inesperados del motor, con espera de 30 s × 2ⁿ (máx. 15 min). Los errores de datos (`content_hash_mismatch`, `content_unavailable`) no se reintentan.
- Probado: orden de etapas, reintentos, lease caducado recuperado por otro worker, lease agotado → `lease_expired`, cancelación antes y durante la ejecución, y 4 workers en paralelo sobre 24 etapas en InnoDB: cada etapa se ejecuta exactamente una vez.
