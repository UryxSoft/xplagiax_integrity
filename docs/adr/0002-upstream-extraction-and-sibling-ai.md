# ADR-0002 — Extracción en appcli2 y análisis de IA en los servicios hermanos

- Estado: Propuesto
- Fecha: 2026-11-13

## Contexto
Según el prompt maestro, appcli2 ya extrae los documentos y enviará el resultado en JSON. Los análisis de IA ya existen en beyond_xota, finderx y scitrace. Duplicar cualquiera de las dos cosas aumenta la RAM, el mantenimiento y el riesgo de que los resultados no coincidan.

## Decisión
- La entrada principal es el **JSON de extracción** (`source_kind = upstream_extraction`). La subida de archivos locales (`local_upload`) existe en el modelo, pero no se implementa hasta que un benchmark demuestre que hace falta (extractor de appcli2 frente a anydoc y LightOnOCR).
- La detección de contenido de IA es un **adaptador** hacia los servicios hermanos. Integrity guarda el modelo y la versión que informen, normaliza la salida a `STATISTICAL_INDICATOR` y no reetiqueta los resultados.

## Consecuencias
- (+) No hay PDF ni OCR en este servicio: menos superficie de ataque y menos memoria.
- (−) Integrity depende de la calidad de la extracción de appcli2. Por eso el JSON debe incluir `extractor_version` y datos de calidad, y el servicio debe rechazar extracciones insuficientes.
- (−) Bloqueo: no se puede implementar sin los contratos reales.
