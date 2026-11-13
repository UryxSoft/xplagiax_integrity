# xplagiax-integrity
An AI-powered document integrity platform by XplagiaX, bringing together patent analysis, scientific paper review, and dissertation certification through shared engines for AI detection, plagiarism analysis, similarity assessment, citation verification, and document intelligence.

## Technical status & quickstart

> **Status: Phase 1 foundation, audited** ([audit](docs/AUDIT_PHASE1.md), [reconciliation](docs/RECONCILIATION_PHASE3.md)). The service skeleton, security base, data model and migrations exist and are tested.
> **No scientific engine is implemented yet.** `GET /api/v1/version` lists each engine's real maturity.
> Architecture: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) · Roadmap: [docs/ROADMAP.md](docs/ROADMAP.md) · Audit: [docs/INITIAL_AUDIT.md](docs/INITIAL_AUDIT.md)

Requirements: Python ≥ 3.12, MySQL 8 (SQLite is accepted outside production).

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt && pip install -e . --no-deps
export XI_ENV=development XI_DATABASE_URL=sqlite:///./instance/dev.sqlite3 && mkdir -p instance
alembic upgrade head
python -m pytest
flask --app integrity.app:create_app integrity create-client --name local --scope platform
flask --app integrity.app:create_app run
curl -s localhost:5000/api/v1/health/ready
```

Optional MySQL integration tests: `XI_TEST_MYSQL_URL=mysql+pymysql://user:pass@host:3306/disposable_db python -m pytest tests/test_mysql_integration.py`.
Configuration reference: [.env.example](.env.example).


# XplagiaX Integrity Platform

**AI-Powered Document, Academic & Intellectual Property Integrity**

[English](#english) | [Español](#español)

---

# English

## 1. Overview

**XplagiaX Integrity Platform** is an intelligent document analysis and integrity ecosystem designed to strengthen trust, originality, transparency, and research quality across academic, scientific, and intellectual property environments.

The platform brings together three specialized products under a shared technological architecture:

1. **Patent Integrity Pass** – Patent document analysis and prior-art intelligence.
2. **Research Paper Review** – Scientific paper analysis and research integrity assessment.
3. **Dissertation Certification** – Dissertation and thesis integrity assessment and certification workflows.

Instead of developing three isolated platforms, XplagiaX Integrity aims to provide a unified ecosystem with reusable analysis engines, shared infrastructure, and specialized product modules.

## 2. Vision

Our vision is to build a comprehensive integrity layer for academic institutions, researchers, inventors, universities, and organizations that depend on reliable documentary and scientific information.

We aim to make document verification and research evaluation more accessible, consistent, transparent, and evidence-driven.

## 3. Products

### 3.1 Patent Integrity Pass

An intelligent patent analysis solution designed to help inventors, researchers, patent professionals, and organizations evaluate patent documentation.

**Core objectives:**
- Extract structured information from patent documents.
- Identify titles, inventors, abstracts, descriptions, claims, drawings, and references.
- Search relevant prior-art information across available patent and scientific sources.
- Compare patent claims against retrieved technical documents.
- Evaluate consistency between claims and patent descriptions.
- Generate traceable reports with source references and supporting evidence.

**Important:** The platform provides technical and documentary analysis. It does not replace professional patent examination or provide legal opinions on patentability, infringement, or freedom to operate.

### 3.2 Research Paper Review

A scientific document analysis solution designed to support researchers, universities, academic reviewers, and scientific institutions.

**Core objectives:**
- Analyze scientific papers and research manuscripts.
- Assess textual similarity and potential plagiarism.
- Identify potentially AI-generated content.
- Examine citations and bibliographic references.
- Identify inconsistencies and potential documentary integrity concerns.
- Support evidence-based research review through structured reports.

### 3.3 Dissertation Certification

A specialized solution for evaluating the documentary and academic integrity of dissertations, theses, and final research projects.

**Core objectives:**
- Analyze dissertations and academic manuscripts.
- Evaluate plagiarism and textual similarity.
- Assess AI-generated content indicators.
- Review citations and references.
- Identify potential inconsistencies in academic documentation.
- Generate structured integrity reports.
- Support certification workflows based on configurable evaluation criteria.

Certification results should be understood as technical assessments based on defined criteria, not absolute guarantees of originality or academic validity.

## 4. Shared Intelligence Engines

The three products are designed to reuse common technological capabilities.

| Engine | Purpose |
|---|---|
| Document Extraction | Extract text and structured information from supported formats. |
| AI Content Detection | Analyze indicators associated with AI-generated content. |
| Plagiarism Analysis | Identify potentially duplicated or unoriginal content. |
| Similarity Analysis | Compare documents, passages, claims, and sources. |
| Citation Analysis | Examine citations and bibliographic references. |
| Academic Search | Retrieve relevant scientific and academic information. |
| Patent Search | Connect to available patent information sources. |
| Report Engine | Generate structured and traceable analytical reports. |
| Certificate Engine | Support document integrity certification workflows. |

These engines are shared capabilities. Each product applies them according to its own domain-specific requirements.

## 5. Architecture

The initial architectural direction is a **modular monolith with independent background workers**.

This approach provides clear product boundaries without introducing unnecessary microservice complexity.

### Architectural principles

- Shared authentication and authorization.
- Reusable analysis services.
- Independent product modules.
- Isolated external data-source adapters.
- Background processing for computationally intensive tasks.
- Centralized document and report management.
- Modular testing and maintainable code boundaries.

### Proposed project structure

> **Superseded:** the tree below was the initial proposal. The implemented layout is the `integrity/` package described in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) §3.

```text
xplagiax-integrity/
│
├── app/
│   ├── core/
│   │   ├── auth/
│   │   ├── database/
│   │   ├── storage/
│   │   └── permissions/
│   │
│   ├── products/
│   │   ├── patent_integrity/
│   │   ├── research_paper/
│   │   └── dissertation/
│   │
│   ├── shared_engines/
│   │   ├── document_extraction/
│   │   ├── ai_detection/
│   │   ├── plagiarism/
│   │   ├── similarity/
│   │   ├── citation_analysis/
│   │   ├── academic_search/
│   │   ├── report_engine/
│   │   └── certificate_engine/
│   │
│   ├── patent_sources/
│   │   ├── epo/
│   │   ├── uspto/
│   │   ├── ip_australia/
│   │   ├── kipris/
│   │   ├── cnipa/
│   │   └── adapters/
│   │
│   └── workers/
│
├── migrations/
├── tests/
├── infrastructure/
│   └── docker/
│
├── docs/
├── config/
├── requirements.txt
└── README.md
```

This is the proposed logical structure. Existing application components should be audited before moving or refactoring code.

## 6. Technology Direction

The architecture is intended to integrate with the existing XplagiaX technology ecosystem.

Potential technology components include:

- **Backend:** Python and Flask.
- **Database:** MySQL and SQLAlchemy.
- **Caching and rate limiting:** Valkey, only when needed. Background work uses a MySQL-backed stage queue ([ADR-0005](docs/adr/0005-background-work.md)).
- **Vector search:** Qdrant.
- **Document storage:** SeaweedFS or compatible object storage.
- **Deployment:** Docker.
- **Background processing:** Independent workers.
- **External integrations:** Patent databases, scientific repositories, and academic information services.

Technology choices and integrations will be validated against performance, licensing, operational cost, and infrastructure constraints.

## 7. External Data Sources

Patent and scientific information retrieval will use independent connectors wherever possible.

Potential patent data sources include:

- European Patent Office (EPO).
- United States Patent and Trademark Office (USPTO).
- IP Australia.
- Korean Intellectual Property Office (KIPRIS).
- Polish Patent Office (UPRP).
- Other national and international patent information providers.

Scientific and academic information sources may include Crossref, PubMed, and arXiv, depending on the specific use case and applicable access conditions.

**Data licensing and compliance:** Public accessibility does not automatically grant permission for commercial API usage, bulk storage, redistribution, or AI processing. Each provider's terms and permissions must be reviewed before integration.

## 8. Security, Privacy and Data Governance

The platform is intended to follow security and privacy principles including:

- Controlled access to documents and analytical reports.
- Secure document transmission and storage.
- Role-based authorization.
- Protection of API credentials and secrets.
- Traceability of analytical operations.
- Data retention and deletion policies.
- Compliance review for external data sources.

Specific security certifications or regulatory compliance should only be claimed after the relevant requirements have been independently verified.

## 9. Development Philosophy

The project follows these principles:

1. Reuse existing, validated components whenever possible.
2. Avoid duplicating shared analysis engines.
3. Keep product-specific business logic isolated.
4. Prefer modularity over unnecessary distributed infrastructure.
5. Preserve backward compatibility when integrating with existing XplagiaX services.
6. Validate performance and resource consumption before introducing new dependencies.
7. Make analytical results traceable and evidence-based.
8. Never treat automated detection results as infallible conclusions.

## 10. Project Status

This repository is intended to consolidate the development of the three integrity products.

Implementation status, supported features, integrations, and release milestones should be documented as they are validated.

Planned capabilities must not be considered production-ready until they have passed implementation and testing.

## 11. Project Ownership

**XplagiaX**

Website: https://xplagiax.ca  
Platform: https://app.xplagiax.ca

**Mission:** Building intelligent tools that strengthen trust, originality, and integrity in academic research, scientific documentation, and intellectual property.

---

# Español

## 1. Descripción general

**XplagiaX Integrity Platform** es un ecosistema inteligente de análisis documental e integridad diseñado para fortalecer la confianza, originalidad, transparencia y calidad de la investigación en los ámbitos académico, científico y de propiedad intelectual.

La plataforma integra tres productos especializados bajo una arquitectura tecnológica compartida:

1. **Patent Integrity Pass** – Análisis de documentos de patentes e inteligencia sobre antecedentes técnicos.
2. **Research Paper Review** – Análisis de artículos científicos y evaluación de integridad investigativa.
3. **Dissertation Certification** – Evaluación de integridad y procesos de certificación de tesis y disertaciones.

En lugar de desarrollar tres plataformas aisladas, XplagiaX Integrity busca ofrecer un ecosistema unificado con motores de análisis reutilizables, infraestructura compartida y módulos especializados por producto.

## 2. Visión

Nuestra visión es construir una capa integral de confianza e integridad para instituciones académicas, investigadores, inventores, universidades y organizaciones que dependen de información documental y científica confiable.

Buscamos hacer que la verificación documental y la evaluación de investigaciones sean más accesibles, consistentes, transparentes y fundamentadas en evidencias.

## 3. Productos

### 3.1 Patent Integrity Pass

Solución inteligente de análisis de patentes diseñada para ayudar a inventores, investigadores, profesionales de patentes y organizaciones a evaluar documentación relacionada con propiedad intelectual.

**Objetivos principales:**
- Extraer información estructurada de documentos de patentes.
- Identificar títulos, inventores, resúmenes, descripciones, reivindicaciones, dibujos y referencias.
- Buscar antecedentes técnicos relevantes en fuentes de patentes y publicaciones científicas disponibles.
- Comparar reivindicaciones con documentos técnicos recuperados.
- Evaluar la consistencia entre las reivindicaciones y las descripciones de una patente.
- Generar informes trazables con referencias y evidencias documentales.

**Importante:** La plataforma proporciona análisis técnico y documental. No sustituye un examen profesional de patentes ni emite opiniones legales sobre patentabilidad, infracción o libertad de operación.

### 3.2 Research Paper Review

Solución de análisis de documentos científicos diseñada para apoyar a investigadores, universidades, revisores académicos e instituciones científicas.

**Objetivos principales:**
- Analizar artículos científicos y manuscritos de investigación.
- Evaluar similitud textual y posibles casos de plagio.
- Identificar indicadores de contenido potencialmente generado mediante IA.
- Examinar citas y referencias bibliográficas.
- Identificar inconsistencias y posibles problemas de integridad documental.
- Facilitar revisiones científicas fundamentadas mediante informes estructurados.

### 3.3 Dissertation Certification

Solución especializada en la evaluación de integridad documental y académica de tesis, disertaciones y trabajos finales de investigación.

**Objetivos principales:**
- Analizar tesis y manuscritos académicos.
- Evaluar plagio y similitud textual.
- Examinar indicadores de contenido generado por IA.
- Revisar citas y referencias bibliográficas.
- Identificar posibles inconsistencias en la documentación académica.
- Generar informes estructurados de integridad.
- Facilitar procesos de certificación mediante criterios de evaluación configurables.

Los resultados de certificación deben entenderse como evaluaciones técnicas basadas en criterios definidos, no como garantías absolutas de originalidad o validez académica.

## 4. Motores de inteligencia compartidos

Los tres productos están diseñados para reutilizar capacidades tecnológicas comunes.

| Motor | Propósito |
|---|---|
| Extracción documental | Extraer texto e información estructurada de formatos compatibles. |
| Detección de contenido IA | Analizar indicadores asociados con contenido generado por IA. |
| Análisis de plagio | Identificar contenido potencialmente duplicado o no original. |
| Análisis de similitud | Comparar documentos, fragmentos, reivindicaciones y fuentes. |
| Análisis de citas | Examinar citas y referencias bibliográficas. |
| Búsqueda académica | Recuperar información científica y académica relevante. |
| Búsqueda de patentes | Conectar con fuentes disponibles de información sobre patentes. |
| Motor de informes | Generar informes analíticos estructurados y trazables. |
| Motor de certificación | Facilitar flujos de evaluación y certificación de integridad documental. |

Estos motores son capacidades compartidas. Cada producto los utiliza de acuerdo con sus propios requisitos y necesidades de dominio.

## 5. Arquitectura

La dirección arquitectónica inicial es un **monolito modular con workers independientes para tareas en segundo plano**.

Este enfoque permite mantener límites claros entre productos sin introducir complejidad innecesaria de microservicios.

### Principios arquitectónicos

- Autenticación y autorización compartidas.
- Servicios de análisis reutilizables.
- Módulos independientes por producto.
- Adaptadores aislados para fuentes externas.
- Procesamiento en segundo plano para tareas de alto consumo computacional.
- Gestión centralizada de documentos e informes.
- Pruebas modulares y separación clara de responsabilidades.

### Estructura propuesta

> **Sustituida:** el árbol siguiente fue la propuesta inicial. La estructura implementada es el paquete `integrity/` descrito en [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) §3.

```text
xplagiax-integrity/
│
├── app/
│   ├── core/
│   │   ├── auth/
│   │   ├── database/
│   │   ├── storage/
│   │   └── permissions/
│   │
│   ├── products/
│   │   ├── patent_integrity/
│   │   ├── research_paper/
│   │   └── dissertation/
│   │
│   ├── shared_engines/
│   │   ├── document_extraction/
│   │   ├── ai_detection/
│   │   ├── plagiarism/
│   │   ├── similarity/
│   │   ├── citation_analysis/
│   │   ├── academic_search/
│   │   ├── report_engine/
│   │   └── certificate_engine/
│   │
│   ├── patent_sources/
│   │   ├── epo/
│   │   ├── uspto/
│   │   ├── ip_australia/
│   │   ├── kipris/
│   │   ├── cnipa/
│   │   └── adapters/
│   │
│   └── workers/
│
├── migrations/
├── tests/
├── infrastructure/
│   └── docker/
│
├── docs/
├── config/
├── requirements.txt
└── README.md
```

Esta es una estructura lógica propuesta. Antes de mover o refactorizar código, se deben auditar los componentes existentes de la aplicación.

## 6. Dirección tecnológica

La arquitectura está pensada para integrarse con el ecosistema tecnológico existente de XplagiaX.

Entre las tecnologías previstas se encuentran:

- **Backend:** Python y Flask.
- **Base de datos:** MySQL y SQLAlchemy.
- **Caché y rate limiting:** Valkey, solo cuando haga falta. El trabajo en segundo plano usa una cola de etapas en MySQL ([ADR-0005](docs/adr/0005-background-work.md)).
- **Búsqueda vectorial:** Qdrant.
- **Almacenamiento documental:** SeaweedFS o almacenamiento de objetos compatible.
- **Despliegue:** Docker.
- **Procesamiento en segundo plano:** Workers independientes.
- **Integraciones externas:** Bases de datos de patentes, repositorios científicos y servicios de información académica.

Las decisiones tecnológicas y las integraciones se validarán considerando rendimiento, licencias, costos operativos y limitaciones de infraestructura.

## 7. Fuentes externas de información

La recuperación de información científica y de patentes utilizará conectores independientes siempre que sea posible.

Entre las posibles fuentes de información sobre patentes se encuentran:

- European Patent Office (EPO).
- United States Patent and Trademark Office (USPTO).
- IP Australia.
- Korean Intellectual Property Office (KIPRIS).
- Polish Patent Office (UPRP).
- Otros proveedores nacionales e internacionales de información sobre patentes.

Las fuentes de información científica y académica pueden incluir Crossref, PubMed y arXiv, dependiendo del caso de uso y de las condiciones de acceso aplicables.

**Licencias y cumplimiento:** Que una fuente sea públicamente accesible no significa que permita automáticamente el uso comercial de su API, el almacenamiento masivo, la redistribución o el procesamiento mediante IA. Las condiciones y autorizaciones de cada proveedor deben revisarse antes de su integración.

## 8. Seguridad, privacidad y gobernanza de datos

La plataforma busca seguir principios de seguridad y privacidad que incluyen:

- Control de acceso a documentos e informes.
- Transmisión y almacenamiento seguros.
- Autorización basada en roles.
- Protección de credenciales y secretos de API.
- Trazabilidad de las operaciones de análisis.
- Políticas de retención y eliminación de datos.
- Revisión de cumplimiento para fuentes externas.

Las certificaciones de seguridad o el cumplimiento normativo específico solo deben declararse una vez verificados independientemente los requisitos correspondientes.

## 9. Filosofía de desarrollo

El proyecto sigue estos principios:

1. Reutilizar componentes existentes y validados siempre que sea posible.
2. Evitar duplicar motores de análisis compartidos.
3. Mantener aislada la lógica de negocio específica de cada producto.
4. Priorizar la modularidad sobre la infraestructura distribuida innecesaria.
5. Preservar la compatibilidad con los servicios existentes de XplagiaX.
6. Validar rendimiento y consumo de recursos antes de incorporar nuevas dependencias.
7. Garantizar que los resultados analíticos sean trazables y estén fundamentados en evidencias.
8. No tratar los resultados de detección automatizada como conclusiones infalibles.

## 10. Estado del proyecto

Este repositorio tiene como objetivo centralizar el desarrollo de los tres productos de integridad.

El estado de implementación, las funcionalidades soportadas, las integraciones y los hitos de lanzamiento deberán documentarse a medida que sean validados.

Las capacidades planificadas no deben considerarse listas para producción hasta completar su implementación y pruebas.

## 11. Propiedad del proyecto

**XplagiaX**

Sitio web: https://xplagiax.ca  
Plataforma: https://app.xplagiax.ca

**Misión:** Desarrollar herramientas inteligentes que fortalezcan la confianza, la originalidad y la integridad en la investigación académica, la documentación científica y la propiedad intelectual.

---

© XplagiaX. All rights reserved.
