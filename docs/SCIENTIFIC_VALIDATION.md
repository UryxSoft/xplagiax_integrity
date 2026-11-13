# Validez científica de los resultados

## 1. Naturaleza epistémica de cada hallazgo

Cada `Finding` declara una `nature` (`domain/enums.py::FindingNature`). El informe muestra cada naturaleza con un formato y un lenguaje distintos:

| Naturaleza | Qué significa | Lenguaje permitido | Lenguaje prohibido |
|---|---|---|---|
| `verified_evidence` | Hecho que una persona puede comprobar (el DOI X apunta al título Y, distinto del citado) | "Se verificó que…" | — |
| `textual_match` | Solapamiento exacto o casi exacto con una fuente identificada | "Coincidencia textual con [fuente], N caracteres" | "plagio" |
| `semantic_similarity` | Proximidad calculada por un modelo | "Similitud semántica con…" | "copiado", "falta de novedad" |
| `statistical_indicator` | Indicador probabilístico (contenido de IA) | "Indicadores asociados a…", con limitaciones | "generado por IA", "fraude", un % no calibrado presentado como probabilidad |
| `structural_observation` | Sección ausente, referencia sin citar… | "Se observó…" | — |
| `not_determinable` | El sistema no pudo concluir | "No determinable porque…" | — |

**Resultados distintos que no deben confundirse** (cada uno es un hallazgo o una limitación distinta):
- `NO MATCH FOUND IN QUERIED SOURCES` ≠ `VERIFIED ORIGINAL CONTENT`. El sistema **nunca** emite lo segundo.
- DOI no encontrado ≠ DOI inexistente ≠ error de consulta ≠ metadatos inconsistentes. `api_requests.outcome` los distingue.
- La API no devolvió resultados ≠ no existe la publicación.

## 2. Confianza

- `findings.confidence` es opcional. Si tiene valor, `confidence_calibrated` debe estar definido (CHECK en la BD).
- Un valor solo se muestra como probabilidad si `confidence_calibrated = true` y hay un informe de calibración (datos, fecha, ECE o un equivalente) asociado a esa versión del motor.
- Un score sin calibrar se muestra como score, con su método, nunca como "X % de probabilidad".

## 3. Límites que no cambian

- No hay conclusiones jurídicas: ni patentabilidad, ni novedad jurídica, ni infracción, ni FTO, ni validez.
- No es una revisión por pares ni garantiza la aceptación editorial.
- Un certificado acredita que **se ejecutó un proceso con criterios definidos sobre un documento con un hash dado**. No acredita originalidad, validez científica ni aceptación por la institución.
- Un indicador de IA nunca basta, por sí solo, para un estado `REQUIRES_CORRECTIONS` o de rechazo en Dissertation: hace falta revisión humana (a confirmar en Fase 2).

## 4. Validación por motor [DISEÑO]

Antes de que un motor pase a `implemented` en `domain/capabilities.py` necesita:
1. Una especificación del método (algoritmo, parámetros, idiomas que soporta).
2. Un corpus de evaluación con licencia verificada y etiquetas documentadas: originales, coincidencias exactas, paráfrasis, citas correctas, referencias incorrectas o inexistentes, documentos multilingües y escaneados.
3. Métricas: precision, recall, F1, FPR y FNR por idioma y tipo de documento. Estabilidad entre ejecuciones (los motores deterministas deben dar el mismo resultado byte a byte).
4. Umbrales iniciales **marcados como provisionales** hasta calibrarlos.
5. Pruebas de regresión con las salidas guardadas.

Las métricas se publican en este archivo por versión de motor. **No se escribe ninguna cifra de precisión sin el informe que la respalde.**

## 5. Estado por motor

| Motor | Método | Validación |
|---|---|---|
| `content_check` v1 | Recalcula el SHA-256 del texto y lo compara con el de la ingesta | Determinista; pruebas unitarias |
| `doi_detection` v1 | Expresión regular conservadora sobre el texto; solo detección | Pruebas de casos positivos y negativos. **Sin métricas sobre un corpus** |
| `citation_consistency` v1 | Localiza la sección de referencias por su encabezado (multilingüe), decide el estilo (numérico o autor-año) y cruza citas con entradas. Autor-año usa solo el primer apellido y el año, sin distinguir acentos ni mayúsculas | Pruebas sobre fragmentos realistas en inglés y español. **Sin precisión ni exhaustividad medidas.** Sus hallazgos son `structural_observation` de severidad `low` y piden confirmación manual |

| `version_diff` v1 | Alineación de párrafos normalizados (difflib) y, en los bloques reescritos, emparejamiento por mayor proporción de secuencias de 5 palabras compartidas, sin cruces. Umbral provisional de 0,2 para considerar un párrafo "modificado" | Recupera exactamente las ediciones de un corpus **sintético** con verdad conocida (`tests/test_version_diff.py`). **Sin validar con tesis reales** |

Riesgos conocidos de `citation_consistency` v1, que el corpus de validación debe medir:
- **Falsos positivos:** citas con formatos no contemplados ("Smith 2020" sin coma ni paréntesis, "[Smith20]"), apellidos compuestos o con partículas ("van der Berg", "de la Cruz"), entradas de referencia de varias líneas que llegan como varios párrafos.
- **Falsos negativos:** varios trabajos del mismo autor y año ("2020a", "2020b") se tratan como uno; corchetes numéricos que no son citas (por ejemplo, intervalos "[0, 1]") pueden contarse como citas.
- Si no encuentra la sección de referencias, **no produce hallazgos** y lo declara como limitación.

Riesgos conocidos de `version_diff` v1:
- Un párrafo partido en dos o dos párrafos fusionados se informan como eliminados y añadidos, no como modificados.
- El umbral de 0,2 es provisional. Una reescritura profunda con las mismas ideas puede quedar por debajo y aparecer como eliminado más añadido.
- Mide coincidencia de palabras, no de contenido ni de calidad.
