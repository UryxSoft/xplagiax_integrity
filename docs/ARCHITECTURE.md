# Arquitectura — XplagiaX Integrity

Estado: **Fase 1 auditada y corregida** (`AUDIT_PHASE1.md`, `RECONCILIATION_PHASE3.md`).
Las secciones marcadas **[DISEÑO]** todavía no tienen código. Las marcadas **[IMPLEMENTADO]** tienen código y pruebas.

## 1. Contexto y responsabilidades

```text
            usuarios finales
                  │  (login, pagos, subida, UI)
                  ▼
         ┌───────────────────┐   JSON de extracción + afirmación de org/usuario
         │  xplagiax_appcli2 │ ─────────────────────────────────────────┐
         └───────────────────┘                                          ▼
                                                    ┌───────────────────────────────┐
                                                    │      XplagiaX Integrity       │
                                                    │  (este repo, monolito modular)│
                                                    └──────┬─────────┬──────────┬───┘
                     ┌───────────────────────────────────┘          │          │
                     ▼                                              ▼          ▼
     beyond_xota / finderx / scitrace                       MySQL (propio)   APIs externas
     (indicadores de contenido IA)                          Valkey (propio)  (Crossref, EPO, USPTO…)
                                                            Qdrant (compartido) / SeaweedFS
```

- **Integrity hace:** orquestar evaluaciones por producto, ejecutar los motores de integridad, consultar fuentes externas autorizadas, guardar hallazgos con su evidencia, generar informes y certificados verificables.
- **Integrity no hace:** autenticar a usuarios finales, cobrar, extraer PDFs como vía principal, ni entrenar o alojar detectores de IA.
- **Límite de confianza:** solo atiende a *clientes de servicio* autenticados (SECURITY.md §3).

## 2. Estilo: monolito modular

Un repositorio, un artefacto desplegable y **dos tipos de proceso a partir del mismo código**:

| Proceso | Qué hace | Estado |
|---|---|---|
| `api` (gunicorn + Flask) | Valida, persiste y encola. **Nunca ejecuta NLP pesado dentro de una petición.** | [IMPLEMENTADO] base |
| `worker` | Toma etapas de la base de datos mediante *leases* y ejecuta los motores | [DISEÑO] ADR-0005 |

No hay microservicios internos. Cada motor es un paquete de Python con una interfaz explícita. Se separaría en otro proceso solo si las mediciones lo justifican (por ejemplo, un OCR que necesite límites de memoria propios).

## 3. Capas y reglas de dependencia

```text
integrity/
├── app.py, config.py, cli.py      composición: factory, settings, comandos de operación
├── core/                          transversal: ids, errores, logging, contexto de petición
├── domain/                        Python puro: vocabularios, estados, inventario de capacidades
├── security/                      claves de API, contexto de organización, auditoría
├── application/                   casos de uso sin Flask; reciben la sesión y no confirman (hoy: alta de organizaciones y usuarios)
├── infrastructure/db/             SQLAlchemy: modelos, sesión, helpers por organización, versión de esquema
├── migrations/                    Alembic
└── api/v1/                        Flask: health, version, auth/context
```

Capas previstas, que se crean **solo cuando tengan código**:

```text
├── engines/<engine>/              motores compartidos (puros respecto a I/O siempre que sea posible)
├── products/{patent_integrity,research_paper,dissertation}/
│                                  workflow (lista de etapas), taxonomía de hallazgos, reglas, esquema del informe
├── integrations/{academic,patents,ai_services}/<provider>/   adaptadores
├── reporting/                     construcción del informe a partir de hallazgos y evidencias
└── workers/                       bucle de leases, ejecutor de etapas
```

Reglas (las del primer grupo las comprueba `tests/test_architecture.py`):

| Capa | Puede importar | No puede importar |
|---|---|---|
| `domain` | stdlib, `domain` | Flask, SQLAlchemy, cualquier otra capa |
| `core` | stdlib, Flask | `infrastructure`, `security`, `api` |
| `infrastructure` | `domain`, `core` | `api` |
| `engines` [DISEÑO] | `domain`, `core` | `api`, `products`, `infrastructure.db` (reciben datos y devuelven resultados) |
| `products` [DISEÑO] | `engines`, `domain`, `application` | otros `products` |
| `api` | todas | — |

Además, ningún módulo puede importar `torch`, `transformers`, `spacy`, `numpy`, `pandas`… sin un ADR (también lo comprueba un test).

**Por qué los productos no se importan entre sí:** Dissertation se parece a Research Paper con capítulos y versiones. La tentación es heredar uno del otro. Lo que comparten debe estar en `engines` o `application`, no un producto dentro de otro.

## 4. Flujo de procesamiento [DISEÑO]

```text
appcli2 ──POST /documents (JSON de extracción v0)──► API
  API: autenticar → resolver org → validar esquema → sha256 canónico → Document + DocumentVersion → 201
appcli2 ──POST /evaluations {product, document_version_id, criteria, Idempotency-Key}──► API
  API: congelar config (config_snapshot + sha256) → Evaluation(PENDING) + EvaluationStages → QUEUED → 202
worker: tomar la siguiente etapa (lease) → ejecutar motor → guardar EvaluationResult + Findings + Evidence
        → siguiente etapa … → consolidación → Report → (Dissertation) evaluación del certificado
appcli2 ──GET /evaluations/{id}──► estado + progreso por etapa
appcli2 ──GET /evaluations/{id}/report──► informe JSON
```

Etapas por producto (orden previsto; cada una apunta a una versión de motor):

| Etapa | Patent | Paper | Dissertation |
|---|---|---|---|
| validación de ingestión / suficiencia de texto | ✓ | ✓ | ✓ |
| normalización + segmentación (con mapa de offsets) | ✓ | ✓ | ✓ por capítulo |
| parser de estructura | claims (indep./dep.), descripción | IMRaD y alternativas | capítulos, perfil de la institución |
| citas ↔ bibliografía | refs. de patente | ✓ | ✓ |
| verificación de DOI / registros | — | ✓ | ✓ |
| búsqueda de antecedentes | APIs de patentes + académicas | académicas | académicas |
| similitud (léxica → semántica) | claims vs. recuperados | fragmentos | fragmentos por capítulo |
| indicadores de IA (servicios hermanos) | ✓ | ✓ | ✓ por capítulo |
| consistencia | claims ↔ descripción | método ↔ resultados ↔ conclusiones | entre capítulos |
| comparación de versiones | — | — | ✓ |
| consolidación de evidencia + informe | ✓ | ✓ | ✓ + certificado |

**Fallo parcial:** si un proveedor no está disponible, la etapa termina como `SKIPPED` o `FAILED` con un `ApiRequest` que registra el resultado, y la evaluación termina como `PARTIALLY_COMPLETED`. El informe lo muestra como una limitación. Nunca se escribe "original" cuando la búsqueda no se hizo.

## 5. Contratos de datos

- **Entrada:** documento de entrada v1, basado en la extracción real de appcli2 (API_CONTRACTS.md §3). [DISEÑO — pendiente de acordar]
- **Salida de un motor:** cada motor devuelve `EngineOutput{engine, version, config_sha256, payload, findings[], limitations[]}`. Los hallazgos llevan `nature` (`FindingNature`), que es lo que impide presentar una similitud o un indicador estadístico como si fuera un hecho. [DISEÑO; los enums ya existen]
- **Informe:** JSON versionado (`schema_version`), generado **solo** a partir de las filas guardadas, sin recalcular nada. Así el informe es reproducible a partir de la base de datos. [DISEÑO]

## 6. Manejo de errores [IMPLEMENTADO base]

- Todas las respuestas de error usan el mismo formato `{"error": {code, message, correlation_id}}` (`integrity/core/errors.py`).
- Excepciones del dominio → 401/403/404/409/422/503. Una excepción no controlada → 500 genérico; el detalle va solo al log.
- Los errores de las etapas se guardan como `error_code` + `error_detail` acotado y saneado (nunca texto del documento ni respuestas de proveedores).
- El *correlation id* sale de `X-Request-ID` si cumple el patrón; si no, se genera uno. Se devuelve en la respuesta y aparece en cada línea de log y en los eventos de auditoría.

## 7. Persistencia

- SQLAlchemy 2.0 directo + Alembic (ADR-0003). MySQL 8 / InnoDB / utf8mb4. Detalle en DATA_MODEL.md.
- **Aislamiento por organización en la base de datos:** claves foráneas compuestas `(x_id, organization_id)` → `(id, organization_id)` en todas las relaciones entre tablas de una organización. Un error en la aplicación no puede enlazar la evaluación de una organización con el documento de otra. Probado en SQLite y en MariaDB.
- Pools de conexión pequeños: 5 + 2 por proceso. Total ≈ procesos × 7.
- La API no importa Alembic: la cabecera de esquema esperada es una constante que un test compara con la cabecera real (ahorra ~10 MB de RSS por worker, PERFORMANCE.md).

**Política de transacciones:** los casos de uso de `application/` reciben la sesión y no confirman; el endpoint (o el worker) confirma una vez al final. Un error revierte todo en el cierre del contexto.

## 8. Estrategia de pruebas

| Nivel | Qué | Estado |
|---|---|---|
| Unitarias | config, ids, máquina de estados, claves, redacción de logs | [IMPLEMENTADO] |
| Integración (SQLite) | migraciones arriba/abajo, paridad modelo↔migración, FKs de organización, auth, CLI, health | [IMPLEMENTADO] |
| Integración (MySQL) | las mismas garantías en un motor real; opcional con `XI_TEST_MYSQL_URL` | [IMPLEMENTADO] (MariaDB 10.11) |
| Arquitectura | límites de importación, prohibición de dependencias pesadas | [IMPLEMENTADO] |
| Contrato | fixtures de JSON de appcli2, mocks de proveedores grabados | [DISEÑO] |
| Validación científica | corpus etiquetado y métricas por motor (SCIENTIFIC_VALIDATION.md) | [DISEÑO] |
| Rendimiento | RSS/CPU/latencia por etapa con documentos de distintos tamaños | [DISEÑO]; mediciones de la base en PERFORMANCE.md |

Las pruebas nunca llaman a proveedores reales. Las pruebas en vivo de los adaptadores serán *opt-in*, como la de MySQL.

## 9. Dependencias

| Paquete | Por qué | Alternativa descartada |
|---|---|---|
| Flask 3.1 | Exigido; ligero | — |
| SQLAlchemy 2.0 | Exigido; usable desde workers sin contexto de Flask | Flask-SQLAlchemy (añade acoplamiento a Flask y no ahorra nada) |
| Alembic 1.16 | Migraciones; solo se carga en CLI y tests | Flask-Migrate (un envoltorio más) |
| PyMySQL 1.1 | Driver de MySQL en Python puro, sin toolchain de C | mysqlclient (más rápido, pero necesita libmysqlclient; reconsiderar con mediciones) |
| cryptography 46 | Lo exige PyMySQL para autenticarse en MySQL 8 (`caching_sha2_password`). Lo detectó el CI: con MariaDB no hacía falta | Usar `mysql_native_password` (obsoleto y desactivado por defecto en MySQL 8.4) |
| gunicorn 23 (extra `server`) | Servidor WSGI de producción | — |
| pytest 8 (dev) | Pruebas | — |

**Se dejaron fuera deliberadamente:** pydantic (se valorará en la Etapa 2 para el esquema de ingestión), cliente de Valkey (hasta que haya rate limiting o caché), Celery/RQ (ADR-0005), structlog (el JSON con stdlib basta), python-dotenv.

## 10. Estado de los componentes

| Componente | Estado | Evidencia |
|---|---|---|
| App factory, config por entorno, rechazo de configuración insegura en producción | Implementado | `test_config.py` |
| Logging JSON, redacción, *correlation id* | Implementado | `test_logging.py`, `test_errors_and_context.py` |
| Errores centralizados | Implementado | `test_errors_and_context.py` |
| Health live/ready (BD + versión de esquema), version | Implementado | `test_health.py` |
| Autenticación de clientes de servicio + contexto de organización/usuario | Implementado | `test_auth.py` |
| Alta de organizaciones y usuarios desde la plataforma | Implementado | `test_tenant_provisioning.py` |
| Convenciones compartidas con la plataforma (hash de texto, organización personal) | Implementado | `test_tenant_provisioning.py` |
| CI con MySQL 8.4 y build de la imagen | Implementado | `.github/workflows/ci.yml` |
| CLI: create-org / create-user / create-client / revoke-client | Implementado | `test_constraints_and_cli.py` |
| Modelo de datos (17 tablas) + migración 0001 | Implementado | `test_migrations.py`, `test_mysql_integration.py` |
| Restricciones de aislamiento y coherencia por organización | Implementado | `test_tenant_isolation.py`, `test_audit_regressions.py` |
| Escritor de auditoría | Base inicial (solo lo usa el CLI) | `test_constraints_and_cli.py` |
| Gestión de evidencias | Base inicial (esquema sí; nada genera evidencias todavía) | — |
| Rate limiting, Valkey | Pendiente | — |
| Ingestión, normalización | Pendiente (bloqueado por el contrato de appcli2) | — |
| Todos los motores científicos | Pendiente / requiere investigación / requiere API externa | `domain/capabilities.py`, `GET /api/v1/version` |
| Workers | Pendiente (ADR-0005) | — |
| Informes, certificados, verificación | Pendiente (el esquema existe) | — |

## 11. Riesgos técnicos

| ID | Riesgo | Prob. | Impacto | Mitigación |
|---|---|---|---|---|
| R1 | Credenciales filtradas en el repo (INITIAL_AUDIT §2) | Ya ocurrió | Crítico | Rotar; usar gestor de secretos |
| R2 | Contrato de appcli2 desconocido → hay que rehacer la ingestión | Alta | Alto | v0 como borrador; acordarlo antes de la Etapa 2 |
| R3 | appcli2 comprometido = acceso total (cliente de plataforma) | Baja | Crítico | Contexto de usuario firmado (SECURITY §3.3), rotación de claves, auditoría |
| R4 | Términos de los proveedores prohíben almacenar, indexar o procesar con IA | Alta | Alto | Flags tri-estado en `external_sources`, adaptadores bloqueados por defecto |
| R5 | Detectores de IA de los servicios hermanos sin calibrar | Alta | Alto | Hallazgos `STATISTICAL_INDICATOR`; mostrar `confidence` solo si está calibrada (forzado por un CHECK) |
| R6 | Qdrant compartido: otros servicios ven datos de Integrity o se mezclan colecciones | Media | Alto | Colecciones propias, filtro por organización obligatorio, ADR antes de usarlo |
| R7 | Tesis grandes desbordan la RAM del worker | Media | Medio | Procesar por capítulos y en streaming; límites duros (PERFORMANCE §4) |
| R8 | La cola en MySQL compite con el tráfico OLTP | Baja | Medio | Índice `(status, lease_expires_at)`; pasar a Valkey si las mediciones lo indican |
| R9 | Solo se probó MariaDB, no MySQL 8 | Media | Bajo | DDL MySQL 8 generado offline en un test; ejecutar `docker compose` + la prueba de MySQL en CI |
| R10 | Desfase de vocabularios (los enums son VARCHAR sin CHECK) | Baja | Bajo | Validación en Python; cambiar un enum exige migración y revisión |
