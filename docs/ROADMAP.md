# Roadmap

Orden de las fases de trabajo: **Fase 1 (Opus, esta) → Fase 2 (auditoría de Fable) → Fase 3 (reconciliación) → Fase 4 (implementación de Sonnet, por etapas)**.
La numeración sigue las Etapas 1–8 del encargo. La auditoría (Fase 2) y su reconciliación (Fase 3) ya están hechas: `AUDIT_PHASE1.md` y `RECONCILIATION_PHASE3.md`.

Orden de los productos: el prompt maestro propone Paper → Dissertation → Patent, porque así se reutiliza más. Tu mensaje lista Patent primero. **Recomiendo ejecutar 5 → 6 → 4 (Paper → Dissertation → Patent):** Patent es lo que más depende de términos de proveedores sin verificar y de métodos de comparación sin validar. Decide tú en la Fase 3.

| Etapa | Contenido | Bloqueos | Criterios de aceptación |
|---|---|---|---|
| **1. Fundación** ✅ | Factory, config, logging, errores, health, auth de servicio, modelo de datos, migración, CLI, pruebas | — | Hecho y auditado: 117 pruebas en SQLite y 133 con MySQL/MariaDB, paridad modelo↔migración, aislamiento por organización probado, CI |
| **1b. Endurecimiento** | Rate limiting (Valkey) por cliente y organización; dos peppers para rotarlo; varias claves por cliente; matriz de roles; contexto de usuario firmado si se decide (A4) | Instancia de Valkey | Petición 429 con `Retry-After` probada; rotación de pepper sin cortes probada; decisión A4 tomada |
| **2. Ingestión** 🟡 | `POST /documents` con el documento de entrada v1 acordado; repositorios con filtro por organización obligatorio (M5); JSON canónico + `content_sha256`; normalización con mapa de offsets; segmentación; detección de idioma (ligera); estado de suficiencia; retención y purga | **Contrato real de appcli2** | Fixtures reales de appcli2 en `tests/fixtures`; ida y vuelta de offsets probada; documento vacío, corrupto o insuficiente → rechazo explícito; mismo JSON → mismo hash; RSS del worker medido con una tesis de 300 páginas |
| **3a. Adaptadores** | Interfaz `SourceAdapter` con capacidades declaradas; Crossref primero; timeouts, reintentos con backoff, circuit breaker, caché según términos; `api_requests` en cada llamada; política SSRF | **Términos verificados** (DATA_SOURCES) y credenciales rotadas | Adaptador bloqueado si los flags no lo permiten (probado); mocks grabados; prueba en vivo *opt-in*; ninguna consulta con texto confidencial |
| **3b. Motores de integridad** | Citas↔bibliografía, DOI, similitud léxica (n-gram/winnowing), cliente de los servicios de IA, gestión de evidencias, motor de informes JSON | Contratos de beyond_xota / finderx / scitrace | Cada motor cumple SCIENTIFIC_VALIDATION §4 antes de marcarse `implemented`; todos los hallazgos tienen evidencia y `nature` |
| **3c. Workers** | Bucle de leases, reintentos, cancelación, recuperación de leases caducados, límites de concurrencia y memoria (ADR-0005) | — | Dos workers no pueden tomar la misma etapa (probado en MySQL); un worker muerto → la etapa se reanuda; cancelar detiene la siguiente etapa |
| **5. Research Paper Review** (primero) | Parser IMRaD y alternativos, workflow, taxonomía, informe | 2, 3a, 3b, 3c | Prueba funcional de principio a fin con un paper con licencia abierta; informe reproducible desde la BD |
| **6. Dissertation Certification** | Capítulos, coherencia entre capítulos, comparación de versiones (reutilizando resultados de secciones sin cambios cuando coincidan motor y configuración), perfiles de criterios | 5 | Tesis con 3 versiones: diferencias correctas y reutilización solo con el mismo `config_sha256` y la misma versión de motor |
| **4. Patent Integrity Pass** (último, ver nota) | Parser de claims (independientes/dependientes), matriz claim↔descripción, búsqueda de antecedentes, informe | 3a (patentes), validar el método de comparación | Claims de patentes publicadas con licencia abierta parseadas con métricas; ninguna afirmación jurídica (revisión del texto del informe) |
| **7. Informes, certificados y verificación** | Esquema de firma (por ejemplo Ed25519, ADR), endpoint público de verificación con rate limit, revocación | ADR de firma aprobado | Certificado alterado → falla la verificación; revocado → se muestra como revocado; el endpoint no expone datos personales |
| **8. Optimización y auditoría final** | Profiling por etapa, pruebas de carga, revisión de dependencias, runbooks, backup | — | p95 por endpoint y RSS por etapa dentro de los presupuestos de PERFORMANCE §3; auditoría adversarial aprobada |

## Pendientes de investigación (no entran en el plan hasta resolverse)

- Qué hacer con los certificados que la plataforma ya emite (INTEGRATION_XPLAGIAX §4).
- Comparar el extractor de appcli2 con `firecrawl/anydoc` y `LightOnOCR-3-0.8B`: necesita el código de appcli2 y un corpus de prueba.
- Similitud de figuras de patentes: método, licencias de las imágenes y coste de CPU.
- Uso de Qdrant compartido: colecciones, filtro por organización y si se permite indexar contenido de terceros.
- Fuente de calibración para los indicadores de IA de los servicios hermanos.

## Estado de la Etapa 2 (2026-11-13)

Hecho: `POST /documents`, versiones, lectura de metadatos, purga, idempotencia (incluida la concurrencia en InnoDB), repositorios con filtro de organización, almacenamiento comprimido con verificación de integridad, cálculo de `retention_until`, mediciones de memoria.

Falta para cerrarla:
- Confirmación del contrato v1 por el equipo de appcli2 y fixtures reales en `tests/fixtures`.
- ~~Normalización con mapa de offsets~~ hecho (`domain/normalization.py`). Falta la segmentación en frases y fragmentos para los motores.
- Proceso periódico de purga por retención.
- Limitar la concurrencia de ingestas grandes (depende del rate limiting, Etapa 1b).
