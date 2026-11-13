# ADR-0004 — Identificadores UUIDv7 y códigos de verificación aleatorios

- Estado: Propuesto
- Fecha: 2026-11-13

## Decisión
- PK = UUIDv7 en CHAR(36). Ordenado por tiempo (inserciones casi secuenciales en el índice clúster de InnoDB) y con 74 bits aleatorios (no enumerable).
- Los códigos públicos de verificación de certificados son independientes de la PK: 16 caracteres de un alfabeto de 30 símbolos sin ambigüedades (~78 bits).

## Alternativas
BIGINT autoincremental + id público aparte (dos columnas e índices por tabla); UUIDv4 (fragmentación del índice); BINARY(16) (más compacto, pero peor de depurar y de leer en los logs).

## Consecuencias
- (−) El id revela el instante de creación con precisión de milisegundos. Se acepta.
- (−) CHAR(36) ocupa más que BINARY(16). Se reconsiderará si el volumen lo exige.
