# Auditoría inicial del repositorio — XplagiaX Integrity

- **Fecha:** 2026-11-13
- **Autor:** Fase 1 — arquitecto principal
- **Rama:** `claude/nice-mayer-11rqnl`
- **Alcance:** contenido del repositorio `UryxSoft/xplagiax_integrity` en el commit `05dc8d3`.

## 1. Estado encontrado

El repositorio **no contenía código**. Solo documentos de planificación:

| Archivo | Contenido | Uso en esta fase |
|---|---|---|
| `README.md` | Visión del producto, estructura propuesta, principios | Se conservó; se le añadió una sección técnica |
| `master_engineering_prompt.md` | Especificación maestra (2.500 líneas) | Fuente principal de requisitos |
| `Prompt_Científico_integridad_patentes.md` | Comité de patent informatics | Requisitos del producto 1 |
| `Prompt_Research_Paper_Review_y_Dissertation_Certification` | Comité de NLP/bibliometría | Requisitos de los productos 2 y 3 |
| `Prompt_Auditor_adversarial_de_producción.md` | Protocolo de auditoría adversarial | Entrada para la Fase 2 |
| `prompt_Arquitecto_científico_auditor_sistemas.md` | Protocolo de auditoría de sistemas | Entrada para la Fase 2 |
| `condigo_referencia_inspiracion.txt` | Notas sobre APIs de libros, código y poemas | Fuera del alcance de los 3 productos |
| `xplagiax_pantents_api_keys.txt` | Notas sobre APIs de patentes **y credenciales reales** | Ver §2 |

No había Flask, modelos, migraciones, pruebas, Dockerfiles ni dependencias. **No hay ningún componente para reutilizar dentro del repositorio.** Los componentes que se pueden reutilizar están en *otros* repositorios de XplagiaX (§4) y no se pudieron inspeccionar.

## 2. Hallazgo crítico de seguridad — credenciales en el repositorio

`xplagiax_pantents_api_keys.txt` (commit `33d4af1`) contiene en texto plano:

- la cuenta y la **contraseña** de un portal de desarrolladores,
- el **Consumer Key y el Consumer Secret de EPO OPS**,
- una cadena que parece una **API key de IP Australia**,
- la dirección de correo de la cuenta.

**Severidad: CRÍTICA.** Aunque el repositorio sea privado, cualquiera con acceso de lectura (personas, integraciones, forks, copias de seguridad) tiene esas credenciales, y además quedan en el historial de Git.

Qué se hizo en esta fase:
- Ningún valor se copió a código, documentación, logs ni commits.
- `.gitignore` bloquea `*_api_keys*.txt`, `.env`, `*.pem` y `*.key` para que no se repita.
- **No** se borró el archivo ni se reescribió el historial: es una acción destructiva que debe decidir el propietario.

Acción necesaria del propietario (en este orden):
1. **Rotar** el secreto de EPO OPS, la contraseña de la cuenta y la clave de IP Australia **ya**. Borrar el archivo no anula las credenciales filtradas.
2. Guardar las credenciales nuevas en un gestor de secretos y pasarlas como variables de entorno (Fase 3).
3. Eliminar el archivo del repositorio y, si se quiere, purgarlo del historial (`git filter-repo`) con un *force push* coordinado.

## 3. Contradicciones entre los documentos de entrada

| # | Contradicción | Resolución propuesta |
|---|---|---|
| C1 | `xplagiax_pantents_api_keys.txt` recomienda *"descargar los conjuntos de datos masivos y construir un índice local en Qdrant"* para EPO LOD. La especificación lo prohíbe (no bulk, no descargas masivas). | **Se aplica la prohibición.** Sin bulk data. |
| C2 | La especificación pide "Redis", pero el prompt maestro dice que Redis lo comparten otros 5 servicios y que **este proyecto debe usar Valkey**. | Valkey dedicado (protocolo Redis), y solo cuando haga falta (ADR-0005). |
| C3 | Tu mensaje pide motores de extracción y OCR; el prompt maestro dice que **xplagiax_appcli2 extrae el documento y envía JSON** a este servicio. | La entrada principal es el JSON de appcli2. La extracción local queda como alternativa pendiente de benchmark (ADR-0002). |
| C4 | Tu mensaje pide un motor de detección de IA; el prompt maestro dice que el análisis de IA lo hacen **xplagiax_beyond_xota / finderx / scitrace**. | Adaptador hacia esos servicios. No se construye un detector nuevo (ADR-0002). |
| C5 | El README propone `app/shared_engines`, `app/patent_sources`…; el prompt maestro propone `app/engines`, `app/integrations`… | Estructura por capas (ARCHITECTURE §3). Solo se crean los módulos que tienen código. |
| C6 | El prompt maestro pide "Analisis de similitud de imagenes o figuras de patentes … por encima del 60%". | Requiere investigación (método, licencias de imágenes, coste de CPU). No entra en el plan hasta que lo valide la auditoría. |
| C7 | El prompt maestro pide valorar `firecrawl/anydoc` y `LightOnOCR-3-0.8B` frente al extractor de appcli2. | Pendiente: hace falta medirlo con documentos reales y con el código de appcli2 (no disponible aquí). |

## 4. Dependencias externas que no se pudieron inspeccionar

| Sistema | Rol para Integrity | Estado |
|---|---|---|
| `xplagiax_appcli2` | Cliente principal; envía extracciones en JSON; es dueño de usuarios y organizaciones | **Contrato JSON desconocido.** El esquema v0 de API_CONTRACTS.md es una *propuesta* |
| `xplagiax_beyond_xota`, `xplagiax_finderx`, `xplagiax_scitrace` | Análisis de IA / búsqueda | Contratos, versiones de modelos y calibración desconocidos |
| Qdrant compartido | Búsqueda vectorial | Uso compartido con appcli2 y finderx; hacen falta colecciones propias y una política de permisos |
| SeaweedFS | Almacenamiento de documentos | Sin datos sobre el despliegue |
| MySQL de producción | Base de datos | Versión no confirmada. Se probó con MariaDB 10.11 y se generó DDL para MySQL 8 sin servidor |

**Riesgo:** hasta conocer el contrato real de appcli2, la ingestión (Etapa 2) no puede terminarse. Es el bloqueo principal.

## 5. Qué se creó en la Fase 1

Ver ARCHITECTURE.md §10 (estado por componente) y CHANGELOG.md. En resumen: base Flask, configuración validada, logging JSON, errores centralizados, health checks, autenticación de servicio con contexto de organización, modelo de datos completo con aislamiento por organización en la base de datos, migración inicial, CLI de operación y 92 pruebas (89 en SQLite + 3 en MariaDB).
