# Seguridad

## 1. Activos

Manuscritos sin publicar, tesis, **invenciones sin presentar** (su divulgación puede destruir la novedad), resultados de evaluación (datos personales sensibles: un indicador de IA asociado a un estudiante), credenciales de proveedores y certificados.

## 2. Controles

| Control | Estado | Dónde |
|---|---|---|
| Configuración insegura bloqueada en producción (pepper, URL de MySQL, sin DEBUG); `XI_ENV` obligatoria | Implementado | `config.py`, `test_config.py` |
| Claves de servicio: 256 bits aleatorios, guardadas como HMAC-SHA256 con pepper, comparación en tiempo constante, se muestran una sola vez | Implementado | `security/api_keys.py`, `cli.py` |
| Comparación HMAC también con prefijos desconocidos (tiempo de respuesta uniforme) | Implementado | `security/auth.py` |
| Revocación y desactivación de clientes | Implementado | `revoke-client`, `test_auth.py` |
| Contexto de organización solo a partir de la credencial; cliente de organización fijado a su organización | Implementado | `security/auth.py` |
| Organización inexistente → 403, no 404 (no se revela cuáles existen) | Implementado | `test_auth.py` |
| FKs compuestas por organización en la BD | Implementado | DATA_MODEL §3 |
| Sin deduplicación entre organizaciones | Implementado (diseño de índices) | DATA_MODEL §3 |
| Límite de tamaño de petición (16 MiB por defecto) | Implementado | `MAX_CONTENT_LENGTH`, `test_errors_and_context.py` |
| Los 500 no revelan detalles internos | Implementado | `core/errors.py` |
| Los errores de BD no incluyen los parámetros SQL (`hide_parameters`) | Implementado | `db/session.py`, `test_audit_regressions.py` |
| Tiempo límite de lectura y escritura en la BD | Implementado | `XI_DB_IO_TIMEOUT_S` |
| Alta de organizaciones y usuarios solo para clientes de plataforma, auditada | Implementado | `api/v1/tenants.py` |
| Redacción de claves sensibles en logs; el access log registra la ruta sin query string; el contenido de los documentos nunca se registra | Implementado (por convención para el contenido) | `core/logging.py` |
| `X-Request-ID` saneado (sin inyección en logs) | Implementado | `core/request_context.py` |
| Cabeceras: `nosniff`, `no-store`, `no-referrer` | Implementado | `app.py` |
| Contenedor sin root | Escrito, sin construir | `Dockerfile` |
| Registro de auditoría (solo inserción) | Base inicial: CLI y alta de organizaciones y usuarios. Los fallos de autenticación van solo al log | `security/audit.py` |
| Rate limiting por cliente y por organización (Valkey) | Pendiente — Etapa 1b | — |
| Validación del esquema de ingestión, límites de bloques | Pendiente — Etapa 2 | API_CONTRACTS §3 |
| Validación de archivos subidos (MIME real, bombas ZIP, PDF malformados) | Pendiente — solo si se habilita `local_upload` | ADR-0002 |
| Protección SSRF en adaptadores (lista de hosts permitidos, sin redirecciones a IPs privadas) | Pendiente — Etapa 3 | — |
| Retención y purga | Pendiente — Etapa 2 | DATA_MODEL §5 |
| Firma de certificados | Pendiente — Etapa 7 | — |

**Path traversal:** el servicio nunca construye rutas a partir de datos de entrada. `original_filename` es solo informativo y el almacenamiento usa `storage_ref` opacos (SeaweedFS). Cuando se implemente la subida local, los nombres de archivo no podrán llegar al sistema de archivos.

## 3. Modelo de confianza

### 3.1 Cliente de plataforma (appcli2)
Puede afirmar cualquier organización o usuario que exista. Es necesario porque appcli2 es el dueño de las identidades. **Consecuencia:** si roban la clave de appcli2, el atacante puede leer cualquier organización. Mitigaciones previstas: rotación de claves (varias claves activas por cliente durante la transición), lista de IPs permitidas en el ingress, red privada entre servicios y alertas de uso anómalo.

### 3.2 Cliente de organización
Para integraciones directas de una institución. Solo puede actuar para su organización (probado).

### 3.3 Mejora propuesta para la Fase 2
Que appcli2 firme por petición un token de corta duración (`org`, `user`, `aud=integrity`, `exp ≤ 60 s`) con una clave distinta de la clave de servicio. Así una clave robada no basta para suplantar a un usuario. Hay que valorar el coste de la integración con appcli2.

### 3.4 Roles
`member`, `reviewer` y `org_admin` existen en el modelo. **Todavía no hay autorización por rol** porque no hay endpoints que la necesiten. Matriz prevista: `member` gestiona sus documentos y evaluaciones; `reviewer` lee los de su organización; `org_admin` gestiona la retención y revoca certificados.

## 4. Secretos

- Solo desde variables de entorno, nunca en el repositorio. `.gitignore` bloquea `.env`, `*_api_keys*.txt`, `*.pem` y `*.key`.
- **El repositorio figura como público en GitHub.** Si no es intencionado, hay que hacerlo privado.
- **Incidente abierto:** hay credenciales reales en `xplagiax_pantents_api_keys.txt` (INITIAL_AUDIT §2). Hay que rotarlas.
- Rotar `XI_API_KEY_PEPPER` invalida todas las claves de servicio. Está previsto soportar dos peppers a la vez para rotarlo sin cortes (Etapa 1b).

## 5. Permisos de la base de datos (producción)

- El usuario de la aplicación tiene `SELECT, INSERT, UPDATE` en las tablas de negocio y `SELECT, INSERT` en `audit_events`, sin `DELETE` ni DDL.
- Las migraciones se ejecutan con otro usuario, desde CI o desde un paso de despliegue.
- La purga por retención la hace un proceso con su propio usuario y su propio registro de auditoría.
