# ADR-0005 — Trabajo en segundo plano: etapas con lease en MySQL; Valkey solo para rate limiting y caché

- Estado: Propuesto (sin implementar)
- Fecha: 2026-11-13

## Contexto
Hace falta procesar en segundo plano, con estado durable por etapa, reintentos, cancelación y recuperación tras un fallo. El estado tiene que vivir en MySQL de todos modos, por trazabilidad. La especificación pide Redis o Valkey solo cuando aporten una ventaja demostrable.

## Decisión
- `evaluation_stages` **es** la cola. Un worker toma una etapa con un `UPDATE … SET status='running', lease_owner=?, lease_expires_at=? WHERE id=? AND status='pending'` condicional (o `SELECT … FOR UPDATE SKIP LOCKED` en MySQL 8) y renueva el lease mientras trabaja. Un lease caducado vuelve a `pending` si `attempt < max_attempts`.
- Sin Celery ni RQ: el estado de la cola y el estado de la evaluación viven en un solo sitio y el sistema de colas no cuesta RAM ni mantenimiento.
- Valkey (instancia propia, no el Redis compartido) se introduce para el rate limiting y la caché de respuestas de proveedores, cuando esas funciones existan.

## Consecuencias
- (+) No hay que reconciliar la cola con la BD. La idempotencia sale de `UNIQUE(evaluation_id, stage_name)`.
- (−) Sondear la tabla de etapas: con un intervalo de 1 a 2 s y un índice `(status, lease_expires_at)` la carga es despreciable con el volumen previsto. Se reconsiderará con mediciones.
- Revisar en la Fase 2: el comportamiento de `SKIP LOCKED` en MySQL 8 frente a MariaDB y el riesgo de dejar de detectar trabajos colgados.
