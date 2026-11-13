# Integración con la plataforma XplagiaX

**Fuente:** inspección de solo lectura de los repositorios `xplagiax_cli` (carpeta `xplagiax_appcli2`, commit `962bfdb`) y `xplagiax_marktrack` (commit `d62bef0`), el 2026-11-13. No se ejecutó ninguno de los dos ni se consultaron sus bases de datos.

Este documento recoge solo lo necesario para integrarse. No reproduce el esquema interno de esos repositorios, que son privados.

## 1. Hechos comprobados

| Tema | Lo que hace la plataforma | Consecuencia para Integrity |
|---|---|---|
| Identidad | Los usuarios tienen id entero. **No existe una entidad de organización**: la institución es un texto en el perfil y un catálogo. marktrack agrupa por espacios de trabajo y aulas, propiedad de un usuario | Cada usuario recibe una organización personal `user:<id>` (§2) |
| Extracción | appcli2 extrae el documento y devuelve **texto plano**, número de palabras, idioma, metadatos, imágenes y un resumen de calidad por páginas (estado `complete` / `partial` / `failed`, páginas con texto, páginas que necesitaron OCR, páginas fallidas). Rechaza documentos con menos de 10 palabras | El contrato de ingestión parte de texto plano, no de bloques con coordenadas (API_CONTRACTS §3) |
| Párrafos | Donde hay granularidad, es la terna `[página, nº de párrafo, texto]` | Las ubicaciones de los hallazgos serán `(página, párrafo)` más offsets de caracteres dentro del párrafo |
| Hash del documento | SHA-256 del texto con los espacios colapsados | `integrity.domain.upstream.text_sha256` usa la misma definición; un hash calculado aquí coincide con el de la plataforma |
| Análisis | La plataforma ya orquesta IA, similitud (FinderX), citas y SciTrace por análisis, con un id de historial (UUID) y resultados en JSON | Integrity puede **recibir** esos resultados en vez de volver a llamar a los servicios. `evaluations.upstream_ref` guarda el id del análisis de la plataforma |
| Cobro | Paquetes de pago único con créditos; un crédito por documento y día, con clave de idempotencia | Integrity no cobra ni cuenta créditos |
| Infraestructura | Redis, Qdrant por HTTP, SeaweedFS (filer + master + bucket), FinderX por URL base y clave. appcli2 **no tiene worker** (usa hilos); marktrack usa Celery | Confirma que hacen falta workers propios (ADR-0005) |
| Certificados | La plataforma **ya emite** certificados de integridad académica con código de verificación público | Solapamiento directo (§4) |

**No comprobado:** la forma exacta de los JSON de resultados de IA, FinderX, citas y SciTrace; los contratos HTTP de `beyond_xota`, `finderx` y `scitrace` (sus repositorios no se inspeccionaron).

## 2. Mapa de identidades

| Plataforma | Integrity |
|---|---|
| Usuario `id = 42` sin institución gestionada | Organización `user:42` + usuario `42` dentro de ella |
| Institución (futuro) | Organización `institution:<id>`, con sus usuarios |

La plataforma da de alta ambos con dos `PUT` idempotentes (API_CONTRACTS §1) antes de la primera evaluación. Con esto el aislamiento de Integrity es, como mínimo, **por usuario**.

## 3. Lo que cambió en Integrity para alinearse

- `domain/upstream.py`: `text_sha256` y `personal_org_ref`.
- `PUT /api/v1/organizations/{ref}` y `PUT /api/v1/organizations/{ref}/users/{ref}`, solo para clientes de plataforma.
- `document_versions.word_count` y `evaluations.upstream_ref`.
- El borrador de extracción v0 (bloques con coordenadas) se sustituyó por una propuesta v1 basada en la forma real.

## 4. Decisión pendiente: dos sistemas de certificados

La plataforma ya emite un certificado con umbrales de similitud y de **porcentaje de IA**. Esto choca con dos reglas de este proyecto:

1. Un indicador de IA no es una prueba de autoría y no debe decidir por sí solo una certificación (`SCIENTIFIC_VALIDATION.md` §3).
2. No debe haber dos motores para lo mismo.

Opciones:

| Opción | Qué implica |
|---|---|
| **A. Integrity sustituye al certificado actual** (recomendada) | Dissertation Certification emite el certificado con criterios versionados y evidencia; la plataforma conserva los ya emitidos y deja de emitir nuevos |
| B. Conviven con nombres distintos | Dos certificados que un usuario confundirá; dos páginas de verificación |
| C. Integrity no emite certificados | Dissertation queda como informe; se retira el modelo `certificates` |

En cualquier caso, recomiendo revisar con negocio el umbral de IA del certificado actual.

## 5. Bloqueos que quedan para la ingestión

- Confirmar con el equipo de appcli2 la propuesta v1 (API_CONTRACTS §3), en especial si enviará párrafos por página o solo texto plano.
- La forma de los JSON de resultados de los servicios de análisis.
- La decisión A4 sobre el contexto de usuario firmado.
