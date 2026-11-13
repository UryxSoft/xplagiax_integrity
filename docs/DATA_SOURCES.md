# Fuentes externas — registro de condiciones

**Regla:** un adaptador solo puede ejecutar una operación si el flag correspondiente de `external_sources` vale `TRUE`. `NULL` (desconocido) equivale a **no permitido**. Todos los proveedores empiezan en `authorization = unverified` y `enabled = false`.

**Estado de la Fase 1:** no se ha verificado ningún término. En esta fase **no** se consultó documentación oficial de los proveedores. La columna "Notas del repo" recoge lo que dicen los archivos del repositorio, y esas notas **no cuentan como verificación**. Revisar los términos es la primera tarea de la Etapa 3 y la debe aprobar una persona (`terms_reviewed_by`).

## 1. Usos que hay que autorizar por separado

| Flag | Pregunta para el proveedor |
|---|---|
| `allows_commercial_use` | ¿Se puede consultar desde un SaaS de pago? |
| `allows_storage` | ¿Se pueden guardar las respuestas? ¿Durante cuánto tiempo (`cache_ttl_seconds`)? |
| `allows_vector_indexing` | ¿Se pueden calcular embeddings y guardarlos en Qdrant? |
| `allows_ai_processing` | ¿Se puede procesar el contenido con modelos de IA, propios o de terceros? |
| `allows_excerpt_display` | ¿Se pueden mostrar fragmentos en el informe del cliente? |
| `allows_redistribution` | ¿Se puede entregar el informe (con datos del proveedor) a terceros? |

Además hay que registrar la licencia (`license_ref`), el texto de atribución, la URL de los términos, la fecha de revisión y los límites de uso oficiales. **Los límites no se inventan:** los rate limits configurados deben citar su fuente.

## 2. Proveedores candidatos

| Código | Proveedor | Notas del repo (sin verificar) | Autorización | Prioridad |
|---|---|---|---|---|
| `crossref` | Crossref REST API | — | UNVERIFIED — PROVIDER CONFIRMATION REQUIRED | Alta (DOI de Paper y Dissertation) |
| `pubmed` | NCBI E-utilities | — | UNVERIFIED | Media |
| `europe_pmc` | Europe PMC REST | — | UNVERIFIED | Media |
| `arxiv` | arXiv API | — | UNVERIFIED | Media |
| `epo_ops` | EPO Open Patent Services | OAuth; "hasta 4 GB/semana gratis para usuarios no pagadores"; servicios biblio / claims / description / family / legal / images | UNVERIFIED | Alta (Patent) |
| `epo_lod` | EPO Linked Open EP Data | "sin API key", "CC BY 4.0", "pensado para consultas ocasionales, no como backend de producción de alto volumen" | UNVERIFIED | Media. La nota de "no apto como backend de alto volumen" exige confirmar si sirve para nuestro patrón de uso |
| `uspto_odp` | USPTO Open Data Portal | "requiere cuenta y API key" | UNVERIFIED | Alta (Patent) |
| `ip_australia` | IP Australia Patent Search API | endpoints `/search/quick` y `/patent/{id}`; entornos test y prod; "sin tarifa de integración; algunas operaciones transaccionales pueden tener cargos" | UNVERIFIED | Baja |
| `uprp` | Oficina Polaca de Patentes (eWyszukiwarka) | solo enlaces a documentación | UNVERIFIED | Baja |
| `jpo` | Japan Patent Office ip-data API | solo una URL | UNVERIFIED | Baja |
| `kipris` | KIPRIS / KIPRISPlus | citado en el prompt maestro | UNVERIFIED | Baja |

**Excluidos por la regla de no usar bulk data ni datasets masivos:** Google Patents Public Datasets (BigQuery), descargas masivas de EPO LOD y datasets de Hugging Face (`patent_metadata.jsonl`, etc.). Se pueden reconsiderar *solo* como corpus de **evaluación** con licencia verificada, nunca como índice de recuperación en producción.

**Fuera de alcance de los 3 productos** (en `condigo_referencia_inspiracion.txt`): Open Library, Gutendex, PoetryDB, GitHub Code Search, Dolos, JPlag, MOSS, Openverse, Wikimedia.

## 3. Credenciales

- Cada adaptador lee sus credenciales de variables de entorno con nombre propio (por ejemplo `XI_EPO_OPS_CONSUMER_KEY`), que se inyectan desde un gestor de secretos. Se definirán en la Etapa 3.
- Las credenciales que hoy están en `xplagiax_pantents_api_keys.txt` **están comprometidas** y deben rotarse antes de usarse (INITIAL_AUDIT §2).
- Hay que confirmar a qué entidad legal pertenecen las cuentas de desarrollador. Una cuenta personal puede no autorizar uso comercial aunque la API sí lo permita.

## 4. Privacidad de las consultas salientes

Las consultas a proveedores se construyen con metadatos y términos mínimos (DOI, título, número de publicación, términos técnicos seleccionados). **No se envía nunca el texto completo de una reivindicación no publicada**: una patente sin presentar es confidencial y una búsqueda en un servicio externo puede considerarse divulgación. `api_requests` guarda la huella de la consulta, no la consulta. Que el usuario pueda consentir búsquedas con texto de las reivindicaciones es una decisión de producto y legal pendiente.
