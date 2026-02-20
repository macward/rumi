# Rumi

Asistente personal de servidor con fines educativos que ejecuta herramientas reales de forma segura mediante Docker sandboxing.

## Características

- **Agente IA**: Ciclo think → act → observe con Groq API (Llama 3.1)
- **Docker Sandbox**: Contenedores aislados sin red, read-only, recursos limitados
- **Herramientas seguras**: bash (allowlist), web_fetch (SSRF protection), web_search (Tavily)
- **Sistema de Skills**: Estrategias reutilizables para tareas complejas
- **Memoria persistente**: Facts que sobreviven entre sesiones
- **Interfaces**: CLI interactivo y bot de Telegram
- **Observabilidad**: Logs JSONL estructurados
- **Sesiones**: Persistencia, locks de concurrencia, TTL configurable

## Requisitos

- Python 3.11+
- Docker Desktop o Docker Engine
- Cuenta en [Groq](https://console.groq.com/) (API key gratuita)
- (Opcional) Bot de Telegram para usar la interfaz de Telegram

## Instalación

### 1. Clonar el repositorio

```bash
git clone https://github.com/tu-usuario/rumi.git
cd rumi
```

### 2. Crear entorno virtual

```bash
python -m venv .venv
source .venv/bin/activate  # Linux/macOS
# o en Windows: .venv\Scripts\activate
```

### 3. Instalar dependencias

```bash
pip install -e ".[dev]"
```

### 4. Construir imagen Docker

```bash
docker build -t rumi-runner:latest -f docker/Dockerfile.runner .
```

### 5. Configurar variables de entorno

```bash
cp .env.example .env
```

Edita `.env` con tus credenciales:

```env
# Requerido
GROQ_API_KEY=tu_api_key_de_groq

# Opcional (solo para Telegram)
TELEGRAM_TOKEN=tu_token_de_telegram

# Opcional: Búsqueda web (Tavily)
TAVILY_API_KEY=tu_api_key_de_tavily

# Opcional: Configuración
GROQ_MODEL=llama-3.1-70b-versatile
SANDBOX_TIMEOUT=30
SANDBOX_MEMORY=512m
```

## Uso

### CLI Interactivo

```bash
rumi
```

```
╔══════════════════════════════════════════╗
║           🦀 Rumi v0.1.0             ║
║    Educational Sandbox Assistant         ║
╚══════════════════════════════════════════╝

Commands:
  /exit, /quit  - Exit the CLI
  /reset        - Reset session (new chat_id)
  /help         - Show this help

you> lista los archivos en /workspace
```

### Bot de Telegram

1. Crea un bot con [@BotFather](https://t.me/BotFather)
2. Copia el token a tu `.env`
3. Ejecuta:

```bash
rumi bot
```

Comandos disponibles en Telegram:
- `/start` - Mensaje de bienvenida
- `/reset` - Reiniciar sesión (limpia contenedor e historial)
- `/stop` - Cancelar operación en curso

## Arquitectura

```
Input (CLI/Telegram) → Agent Loop → ToolRegistry → SandboxManager → Docker
                          ↓
                     LLM (Groq API)
```

### Componentes

| Componente | Descripción |
|------------|-------------|
| `AgentLoop` | Ciclo think→act→observe con circuit breakers |
| `ToolRegistry` | Registro y dispatch de herramientas |
| `SandboxManager` | Gestión de contenedores Docker |
| `SessionManager` | Estado, locks y persistencia por sesión |
| `MemoryManager` | Memoria persistente de facts sobre el usuario |
| `SkillManager` | Sistema de skills reutilizables |
| `BashTool` | Ejecución segura de comandos bash |
| `WebFetchTool` | Fetch HTTP con protección SSRF |
| `WebSearchTool` | Búsqueda web con Tavily API |
| `JSONLLogger` | Logs estructurados para observabilidad |

### Seguridad del Sandbox

Cada contenedor se ejecuta con:

```
--read-only              # Sistema de archivos read-only
--cap-drop=ALL           # Sin capabilities
--security-opt=no-new-privileges
--pids-limit=128         # Límite de procesos
--cpus=1                 # 1 CPU
--memory=512m            # 512MB RAM
--network=none           # Sin red
--user=1000:1000         # Usuario no-root
```

El workspace (`/workspace`) es el único directorio escribible y persiste durante la sesión.

### Herramientas Disponibles

#### bash

Ejecuta comandos en el contenedor. Comandos permitidos (verificados en imagen Docker):

```
ls, cat, head, tail, less, more, cp, mv, rm, mkdir, rmdir, touch, find, which,
stat, du, df, grep, egrep, fgrep, sed, awk, gawk, cut, sort, uniq, wc, tr, tee,
diff, comm, join, paste, echo, printf, yes, base64, md5sum, sha256sum, pwd,
basename, dirname, realpath, date, cal, expr, seq, sleep, true, false, test,
env, printenv, id, whoami, tar, gzip, gunzip, zcat, sh
```

**No permitido**:
- Pipes (`|`), redirecciones (`>`), encadenamiento (`&&`, `;`)
- Sustitución de comandos (`$(...)`, backticks)
- curl, wget, nc, python, ruby, perl, php
- `cd` (es builtin, usar `sh -c 'cd dir && ...'` si necesario)

#### web_fetch

Obtiene contenido de URLs públicas. Protecciones SSRF:

- Solo HTTP/HTTPS (bloquea file://, ftp://, etc.)
- Resuelve DNS y valida IP antes de conectar
- Bloquea IPs privadas (127.0.0.0/8, 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, 169.254.0.0/16)
- **Valida cada redirect** para prevenir bypass SSRF
- Límite de bytes (1MB)
- Timeout configurable

#### web_search

Búsqueda web usando [Tavily API](https://tavily.com/), optimizada para agentes IA:

- Requiere `TAVILY_API_KEY` en `.env`
- Retorna resultados limpios (no HTML crudo)
- Incluye respuesta resumida opcional
- Modos: `basic` (rápido) y `advanced` (profundo)
- Filtros por dominio y tópico

## Estructura del Proyecto

```
rumi/
├── src/rumi/
│   ├── agent/           # AgentLoop, PromptBuilder
│   │   ├── loop.py      # Ciclo principal del agente
│   │   └── prompt.py    # Construcción de prompts
│   ├── tools/           # Herramientas
│   │   ├── base.py      # Interfaz Tool, ToolResult
│   │   ├── registry.py  # ToolRegistry
│   │   ├── bash.py      # BashTool
│   │   ├── web_fetch.py # WebFetchTool
│   │   └── web_search.py # WebSearchTool (Tavily)
│   ├── memory/          # Sistema de memoria persistente
│   │   ├── store.py     # MemoryStore (SQLite)
│   │   ├── extractor.py # FactExtractor (LLM)
│   │   ├── manager.py   # MemoryManager
│   │   └── tools.py     # RememberTool, ForgetTool
│   ├── skills/          # Sistema de skills
│   │   ├── manager.py   # SkillManager
│   │   ├── base.py      # Skill base classes
│   │   ├── parser.py    # SKILL.md parser
│   │   ├── cli.py       # CLI: rumi skills ...
│   │   └── bundled/     # Skills incluidos
│   ├── sandbox/         # Docker sandbox
│   │   └── manager.py   # SandboxManager
│   ├── session/         # Gestión de sesiones
│   │   └── manager.py   # SessionManager
│   ├── telegram/        # Bot de Telegram
│   │   └── bot.py       # TelegramBot
│   ├── cli.py           # CLI interactivo
│   ├── logging.py       # JSONL logging
│   └── main.py          # Entry point
├── docker/
│   └── Dockerfile.runner  # Imagen del sandbox
├── tests/               # Tests
├── pyproject.toml       # Dependencias
└── .env.example         # Template de configuración
```

## Configuración Avanzada

### Variables de Entorno

| Variable | Default | Descripción |
|----------|---------|-------------|
| `GROQ_API_KEY` | (requerido) | API key de Groq |
| `TELEGRAM_TOKEN` | (opcional) | Token del bot de Telegram |
| `TAVILY_API_KEY` | (opcional) | API key de Tavily para web_search |
| `GROQ_MODEL` | `llama-3.1-70b-versatile` | Modelo a usar |
| `SANDBOX_TIMEOUT` | `30` | Timeout de comandos (segundos) |
| `SANDBOX_MEMORY` | `512m` | Límite de memoria del contenedor |
| `SANDBOX_CPUS` | `1` | Límite de CPUs |

### Directorios

Rumi crea los siguientes directorios en `~/.rumi/`:

```
~/.rumi/
├── workspace/{chat_id}/     # Workspace por sesión (montado en /workspace)
├── sessions/{chat_id}.json  # Estado persistido de sesiones
├── skills/                  # Skills del usuario
├── memory.db                # Base de datos SQLite de facts
├── config.json              # Configuración de skills
└── logs/logs.jsonl          # Logs estructurados
```

### Ciclo de Vida de Contenedores

- **Startup**: Limpia contenedores huérfanos (`rumi-runner-*`)
- **Por sesión**: Un contenedor por `chat_id`, creado on-demand
- **Reset/Exit**: Destruye el contenedor de la sesión
- **TTL**: Sesiones expiran después de 1 hora de inactividad (configurable)

### Circuit Breakers

El agente se detiene automáticamente si:

- Mismo tool_call repetido 2 veces consecutivas
- 3 errores consecutivos
- Alcanza max_turns (default: 10)

## Sistema de Skills

Skills son estrategias reutilizables que guían al agente en tareas complejas. A diferencia de Tools (capacidades atómicas), Skills representan flujos de trabajo.

### Tipos de Skills

- **PromptSkill**: Solo `SKILL.md` con instrucciones
- **CodeSkill**: `SKILL.md` + `skill.py` con lógica Python

### Comandos CLI

```bash
rumi skills list              # Listar skills disponibles
rumi skills info <name>       # Ver detalles de un skill
rumi skills enable <name>     # Habilitar skill
rumi skills disable <name>    # Deshabilitar skill
rumi skills create <name>     # Crear skill desde template
```

### Directorios de Skills

Por orden de prioridad:
1. `bundled/` - Skills incluidos en el paquete
2. `~/.rumi/skills/` - Skills del usuario
3. `./skills/` - Skills del proyecto (mayor prioridad)

Ver [docs/skills-system.md](docs/skills-system.md) para documentación completa.

## Sistema de Memoria

Rumi implementa memoria de dos capas:

### Session Memory (temporal)
- Historial de conversación por chat
- Contexto key-value
- Expira después de 1 hora de inactividad

### Facts Memory (persistente)
- Hechos estables sobre el usuario
- Almacenados en SQLite (`~/.rumi/memory.db`)
- Sobreviven entre sesiones

### Herramientas de Memoria

```
remember(key="nombre", value="se llama Juan")  # Guardar fact
forget(key="trabajo")                           # Olvidar facts
```

Los facts se inyectan automáticamente en el prompt del agente.

Ver [docs/memory-system.md](docs/memory-system.md) para documentación completa.

## Desarrollo

### Ejecutar Tests

```bash
# Todos los tests
pytest

# Con coverage
pytest --cov=rumi

# Tests específicos
pytest tests/test_sandbox.py -v
```

### Linting

```bash
ruff check src/
ruff format src/
```

### Agregar una Nueva Herramienta

1. Crea una clase que implemente `Tool`:

```python
from rumi.tools import Tool, ToolResult

class MyTool(Tool):
    @property
    def name(self) -> str:
        return "my_tool"

    @property
    def description(self) -> str:
        return "Descripción para el LLM"

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "param1": {"type": "string", "description": "..."},
            },
            "required": ["param1"],
        }

    async def execute(self, param1: str, **kwargs) -> ToolResult:
        # Implementación
        return ToolResult(success=True, output="resultado")
```

2. Regístrala en el `ToolRegistry`:

```python
registry.register(MyTool())
```

## Logs

Los logs se escriben en formato JSONL en `~/.rumi/logs/logs.jsonl`:

```json
{"timestamp": "2024-01-15T10:30:00Z", "event": "command", "chat_id": "cli-abc123", "argv": ["ls", "-la"], "exit_code": 0, "duration_ms": 45.2}
{"timestamp": "2024-01-15T10:30:01Z", "event": "agent_stop", "chat_id": "cli-abc123", "stopped_reason": "complete", "turns": 2}
```

Campos comunes:
- `timestamp`: ISO 8601
- `event`: tipo de evento
- `chat_id`: identificador de sesión
- `duration_ms`: duración en milisegundos
- `exit_code`: código de salida (para comandos)
- `stopped_reason`: razón de parada del agente

## Troubleshooting

### "GROQ_API_KEY not set"

Asegúrate de tener el archivo `.env` con tu API key o exporta la variable:

```bash
export GROQ_API_KEY=tu_api_key
```

### "Cannot connect to Docker"

Verifica que Docker esté corriendo:

```bash
docker ps
```

### "Image not found: rumi-runner"

Construye la imagen:

```bash
docker build -t rumi-runner:latest -f docker/Dockerfile.runner .
```

### Contenedores huérfanos

Limpia contenedores de Rumi:

```bash
docker rm -f $(docker ps -aq --filter "name=rumi-runner-")
```

## Licencia

MIT

## Contribuir

1. Fork el repositorio
2. Crea una rama (`git checkout -b feature/mi-feature`)
3. Commit tus cambios (`git commit -am 'Add mi feature'`)
4. Push a la rama (`git push origin feature/mi-feature`)
5. Abre un Pull Request
