# ADR-0001 — Monolito modular con API y workers

- Estado: Propuesto (pendiente de auditoría de la Fase 2)
- Fecha: 2026-11-13

## Contexto
Tres productos que comparten la mayoría de los motores. El equipo es pequeño, la infraestructura es de bajo coste y solo se usa CPU. XplagiaX ya opera varios servicios (appcli2, finderx, scitrace, beyond_xota, marktrack).

## Decisión
Un único servicio desplegable (`xplagiax-integrity`) con dos tipos de proceso a partir del mismo código: `api` (Flask/gunicorn) y `worker`. Los productos y los motores son paquetes internos con límites de importación que comprueban los tests. No hay microservicios internos.

## Consecuencias
- (+) Una base de datos, un despliegue y transacciones locales para guardar la evidencia.
- (+) Los motores se comparten llamando funciones, sin serializar entre servicios.
- (−) Un motor que consuma mucha memoria afecta a su worker. Mitigación: límites por proceso y, si las mediciones lo piden, una cola dedicada para ese motor.
- Se separaría un motor en otro servicio solo con mediciones que lo justifiquen.
