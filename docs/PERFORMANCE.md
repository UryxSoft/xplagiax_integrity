# Rendimiento y consumo de recursos

**Regla:** aquí solo se registran números medidos, con su entorno y su método. Los presupuestos (§3) son objetivos, no resultados.

## 1. Mediciones de la base (Fase 1)

Entorno: contenedor Linux x86_64 con 4 vCPU y 16 GB, Python 3.13.18, MariaDB 10.11.14 local (TCP 127.0.0.1), `XI_ENV=production`, `XI_LOG_LEVEL=WARNING`. Fecha: 2026-11-13. Es un entorno de desarrollo compartido, así que las latencias son orientativas.

| Métrica | Valor | Método |
|---|---|---|
| Tiempo de `create_app()` (imports incluidos) | 0,32 s | `time.perf_counter()` alrededor de import + factory |
| RSS de un proceso tras `create_app()` | 54,8 MB | `/proc/self/status` VmRSS |
| RSS tras 500 `GET /health/ready` (en proceso) | 56,3 MB | igual |
| Latencia media de `/health/live`, en proceso (sin red) | 0,23 ms | 2.000 peticiones con `test_client` |
| Latencia media de `/health/ready`, en proceso (consulta a MariaDB) | 0,79 ms | 500 peticiones con `test_client` |
| RSS del master de gunicorn (sin `--preload`) | 20,6 MB | VmRSS del pid del master |
| RSS de cada worker de gunicorn tras 200 `/health/ready` por HTTP | 57,5 MB | VmRSS de los hijos |
| **Total del servicio API con 2 workers** | **≈ 136 MB** | master + 2 workers |

### Optimización medida
La primera versión del health check de *readiness* importaba Alembic para conocer la cabecera de esquema. Con eso, un worker pasaba de 56,6 MB a **67,7 MB** tras sus primeras peticiones. Se cambió por una constante (`infrastructure/db/schema_version.py`) que un test compara con Alembic. El worker se queda ahora en **57,5 MB** (−10 MB por worker). Un test (`test_web_process_does_not_import_alembic`) impide que vuelva a pasar.

### 1.2 Ingestión (Etapa 2)

Mismo entorno, MariaDB 10.11. Un proceso, una petición `POST /documents` con texto de palabras aleatorias (comprime peor que texto real, así que el tamaño guardado es pesimista). "Δ pico" es el aumento del RSS máximo del proceso durante la petición.

| Documento | Cuerpo | Δ pico de RSS | Tiempo | Guardado (zlib) | Resultado |
|---|---|---|---|---|---|
| 10.000 palabras (~11 págs.) | 0,15 MB | +2 MB | 0,04 s | 0,09 MB | 201 |
| 100.000 palabras (~105 págs.) | 1,5 MB | +11 MB | 0,28 s | 0,89 MB | 201 |
| 300.000 palabras (~313 págs.) | 4,6 MB | +36 MB | 0,57 s | 2,7 MB | 201 |
| 600.000 palabras (~626 págs.) | 9,1 MB | +72 MB | 1,08 s | 5,3 MB | 201 |
| 900.000 palabras (~938 págs.) | 13,7 MB | +55 MB | 0,15 s | — | 422 (supera 5 M caracteres) |

Conclusiones:
- El pico crece unas **8 veces el tamaño del cuerpo**: Flask decodifica el JSON entero y luego se construyen el texto, los párrafos y el blob comprimido.
- Una tesis típica (80.000–100.000 palabras) cuesta unos +11 MB. Cabe en el presupuesto del worker de la API.
- Una petición en el límite puede añadir del orden de +75–100 MB. Con 2 workers, dos peticiones así a la vez superan el presupuesto de 80 MB por worker: **hace falta limitar la concurrencia de ingestas grandes** (rate limiting, Etapa 1b) o aceptar `paragraphs` sin duplicar el texto (API_CONTRACTS §3).
- El rechazo por tamaño ocurre **después** de leer el JSON. Por eso el tope de cuerpo se bajó de 16 a 12 MiB: así coincide con el límite de texto y no se gasta memoria en cuerpos que se van a rechazar de todos modos.

Script: `scripts/bench_ingest.py <url-de-bd-desechable> <palabras>` (borra la base de datos de destino).

### 1.3 Normalización de texto

Texto sintético de 300.000 palabras (2,26 M caracteres, ~313 páginas). Tiempo: mejor de 3 ejecuciones, **sin** `tracemalloc` activo. Memoria: pico de asignaciones con `tracemalloc` en una ejecución aparte.

| Implementación | ASCII | ~25 % de palabras con acentos | Pico de memoria |
|---|---|---|---|
| Por carácter (primera versión, hoy referencia en `tests/`) | 0,82 s | 1,17 s | 122 MB |
| Por palabra + offsets en `array('I')` | 0,58 s | 0,73 s | 70 MB |
| Además, iterador con una palabra de adelanto (versión actual) | **0,41 s** | **0,72 s** | **31 MB** |

- El resultado (texto + mapa de offsets) ocupa unos 11 MB para ese documento.
- Una primera medición mostró ~5 s porque se tomó el tiempo con `tracemalloc` activo. **Tiempo y memoria se miden por separado.**
- **Python o Rust:** con 0,4–0,7 s para una tesis de 300 páginas, la normalización no es un cuello de botella frente a las llamadas a APIs externas. No hay motivo medible para reescribirla en Rust. Se reconsiderará si el profiling de un motor real la señala.
- La versión optimizada se compara con la de referencia en 6.000 entradas aleatorias (texto y offsets idénticos): `tests/test_normalization.py`.

### 1.4 Worker

Tesis sintética de 300.000 palabras con 600 DOI, MariaDB, un proceso:

| Etapa | Tiempo | Δ RSS |
|---|---|---|
| `content_check` (descomprimir, verificar hash, resumen) | 0,14 s | +5 MB para ambas etapas |
| `doi_detection` | 0,07 s | |

Los motores actuales son baratos. Las cifras de motores reales (similitud, citas) se añadirán cuando existan.

`version_diff` (dos versiones, 10 % de párrafos editados y 20 eliminados; tiempo sin `tracemalloc`, memoria en una ejecución aparte):

| Palabras por versión | Párrafos | Tiempo | Pico de memoria |
|---|---|---|---|
| 100.000 | 834 | 0,96 s | 30 MB |
| 300.000 | 2.500 | 2,92 s | 61 MB |

Es el motor más caro hasta ahora, y sigue siendo pequeño para un proceso en segundo plano.

### Sin medir todavía
Percentiles p50/p95/p99 bajo carga concurrente (también de la ingestión), throughput, CPU por petición, conexiones a MySQL bajo carga, imagen Docker (no hay daemon en esta sesión) y MySQL 8 real (solo se probó MariaDB).

## 2. Cómo medir

| Qué | Herramienta | Comando / nota |
|---|---|---|
| RSS y pico por proceso | `/proc/<pid>/status` (VmRSS, VmHWM) | sin dependencias |
| Asignaciones de memoria por línea | `tracemalloc` (stdlib) | snapshot antes y después de una etapa |
| CPU y memoria por línea | Scalene | `scalene --cli --memory -m integrity.workers…` (solo en desarrollo, no se instala en producción) |
| Perfil en producción sin parar el proceso | py-spy | `py-spy record -p <pid>` (fuera de la imagen) |
| Latencia HTTP p50/p95/p99 | `wrk` o `hey` contra gunicorn | 30 s, concurrencia 1/4/16 |
| Conexiones a MySQL | `SHOW STATUS LIKE 'Threads_connected'` | comparar con workers × (pool + overflow) |
| Por etapa (Etapa 2+) | métricas propias en `evaluation_stages` (`started_at`, `finished_at`) + RSS pico del worker en `EvaluationResult.payload.resources` | permite ver qué etapa consume qué |

Las pruebas de rendimiento futuras (`tests/performance/`) serán *opt-in*, guardarán sus resultados en JSON y se compararán con los presupuestos de §3.

## 3. Presupuestos iniciales (objetivos que hay que validar)

| Proceso | RSS objetivo | Notas |
|---|---|---|
| Worker de la API (gunicorn sync) | ≤ 80 MB | hoy 57,5 MB; queda margen para validación del esquema y rate limiting |
| Worker de evaluación, en reposo | ≤ 90 MB | sin modelos cargados |
| Worker de evaluación, pico por etapa | ≤ 400 MB para una tesis de 300 páginas | por capítulos y en streaming; límite duro con `RLIMIT_AS` o cgroup |
| Modelos locales | ninguno por defecto | un modelo necesita ADR + mediciones + carga diferida, una instancia por proceso |

## 4. Medidas de diseño para bajo consumo

- Nada pesado dentro de una petición: la API valida, guarda y encola.
- Procesar las tesis por capítulo; no tener en memoria el documento completo y todos sus resultados a la vez.
- Los motores reciben iteradores de bloques, no listas copiadas.
- Concurrencia de workers configurable (por defecto 1 proceso, 1 etapa a la vez). **No** se crea un worker por CPU.
- Caché de respuestas de proveedores solo donde los términos lo permitan (`cache_ttl_seconds`), con clave por huella de la consulta.
- `--max-requests` en gunicorn para limitar el crecimiento lento de memoria.
- Cada dependencia nueva se justifica con mediciones antes y después (el test de arquitectura bloquea las pesadas).
