# Rumi --- Plan v1.2 (MVP con Docker Sandbox)

## Objetivo

Asistente personal de servidor con fines educativos, ejecutando tools
reales de forma segura y aislada mediante Docker.

------------------------------------------------------------------------

# 0. Decisiones Arquitectónicas

## 0.1 Modelo de ejecución

-   Una ejecución activa por `chat_id`
-   Lock por sesión
-   Mensajes concurrentes devuelven: "⏳ ya estoy trabajando"

## 0.2 Docker Sandbox obligatorio

-   1 contenedor por sesión (`rumi-runner-{chat_id}`)

-   Se crea on-demand y se destruye al expirar sesión o con `/reset`

-   Workspace por sesión montado como volumen:

    \~/.rumi/workspace/{chat_id} -\> /workspace

## 0.3 Flags de seguridad del contenedor

-   `--read-only`
-   `--cap-drop=ALL`
-   `--security-opt=no-new-privileges`
-   `--pids-limit=128`
-   `--cpus=1`
-   `--memory=512m`
-   `--user=1000:1000`
-   `--workdir=/workspace`
-   `--network=none`

------------------------------------------------------------------------

# 1. Tooling con Docker

## 1.1 bash tool

-   Ejecutado vía `docker exec`
-   Parsing con `shlex.split()`
-   `shell=False`
-   No soporta: pipes, redirecciones, &&, ;
-   Validación estricta de allowlist
-   Timeout duro

## 1.2 file_read / file_write

Recomendado MVP: - No tools separados - Usar comandos dentro del
contenedor (cat, tee, etc.)

## 1.3 web_fetch

-   Corre en el host
-   Bloqueo SSRF:
    -   Loopback
    -   IP privadas
    -   Link-local
-   Límite de bytes
-   Timeout

------------------------------------------------------------------------

# 2. Circuit Breakers

El loop se corta si: - Se repite el mismo tool_call 2 veces - 3 errores
consecutivos - max_turns alcanzado

------------------------------------------------------------------------

# 3. Observabilidad mínima

Logs JSONL con: - container_id - argv ejecutado - duración - exit_code -
truncated - stopped_reason

------------------------------------------------------------------------

# 4. Fases

## Fase 1 --- Core + Parser

Loop estable + CLI + logs

## Fase 2 --- Docker Sandbox

-   Imagen propia rumi-runner
-   SandboxManager
-   bash vía docker exec
-   workspace por sesión

## Fase 3 --- web_fetch seguro

## Fase 4 --- Sessions persistentes

## Fase 5 --- Telegram + /stop + /reset

------------------------------------------------------------------------

# Riesgos conocidos

1.  LLM puede tomar malas decisiones.
2.  Docker reduce riesgo pero no es aislamiento absoluto.
3.  Bugs en validación pueden abrir escapes.
4.  Sin red en contenedor, dependés del host para web.

------------------------------------------------------------------------

# Decisiones clave

-   Contenedor sin red
-   Sin curl en imagen
-   Sin bash -c
-   Workspace único por sesión
