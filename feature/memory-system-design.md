# Memory System Design — Rumi

## Problem Statement

Rumi no recuerda nada entre conversaciones. Cada sesión arranca desde cero:
no sabe cómo te llamás, en qué trabajás, ni qué le pediste ayer. Para un
agente personal, esto es inaceptable.

Personality Lab demostró que un sistema de facts inyectados en el prompt
funciona bien. Pero tuvo problemas:

- **Whitelist rígida**: solo 13 keys permitidas, inflexible para nuevos tipos
- **Episodes inútiles**: se acumulaban sin aportar valor real
- **Supabase como storage**: dependencia externa innecesaria para un agente local
- **Sin búsqueda**: cargaba todo o nada

Para Rumi necesitamos algo más simple y flexible.

## Decisiones Clave

```
De Personality Lab MANTENER:
  ✓ Facts como key-value
  ✓ Inyección en prompt (bloque MEMORY)
  ✓ Extracción automática vía LLM

De Personality Lab DESCARTAR:
  ✗ Episodes (acumulaban ruido)
  ✗ Whitelist rígida de keys
  ✗ Supabase (reemplazar con SQLite)
  ✗ CERT threshold para extracción

NUEVO en Rumi:
  + Keys flexibles (el LLM decide)
  + SQLite local (zero dependencias)
  + Comando explícito ("recordá que...")
  + Extracción al cerrar sesión (no por turno)
```

## Arquitectura

```
┌──────────────────────────────────────────────────────────────┐
│                     CONVERSACIÓN                              │
│                                                               │
│  User ──► AgentLoop ──► LLM ──► Response                     │
│               │                                               │
│               │ (al inicio)                                   │
│               ▼                                               │
│        MemoryManager.load_all()                               │
│               │                                               │
│               ▼                                               │
│        Inyectar en system prompt                              │
│        como bloque <memory>                                   │
│                                                               │
└──────────────────────────────────────────────────────────────┘
                          │
                          │ (al cerrar sesión)
                          ▼
┌──────────────────────────────────────────────────────────────┐
│                     EXTRACCIÓN                                │
│                                                               │
│  Conversación completa ──► LLM (extract prompt)               │
│                                    │                          │
│                                    ▼                          │
│                             Lista de facts                    │
│                                    │                          │
│                                    ▼                          │
│                           MemoryManager.save()                │
│                                    │                          │
│                                    ▼                          │
│                           SQLite (~/.rumi/memory.db)          │
│                                                               │
└──────────────────────────────────────────────────────────────┘
```

## SQLite Schema

```sql
CREATE TABLE IF NOT EXISTS facts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    key         TEXT NOT NULL,              -- flexible, no whitelist
    value       TEXT NOT NULL,
    source      TEXT NOT NULL DEFAULT 'auto',  -- 'auto' | 'explicit'
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(key, value)                     -- dedup: misma key+value no se repite
);

CREATE INDEX IF NOT EXISTS idx_facts_key ON facts(key);
```

**Notas sobre el schema:**
- Sin `user_id`: Rumi es single-user por diseño (agente personal)
- `UNIQUE(key, value)` previene duplicados exactos
- `source` distingue extracción automática de memorias explícitas
- Keys flexibles: "nombre", "trabajo", "proyecto_actual", "prefiere_typescript",
  lo que el LLM considere relevante

## Interfaces Core

### Fact

```python
@dataclass(frozen=True)
class Fact:
    """Un hecho almacenado en memoria."""
    id: int | None = None     # None para facts nuevos
    key: str
    value: str
    source: str = "auto"      # "auto" | "explicit"
    created_at: str | None = None
    updated_at: str | None = None
```

### MemoryStore

```python
class MemoryStore:
    """Acceso a SQLite para facts."""

    def __init__(self, db_path: Path): ...

    # === CRUD ===
    def save_fact(self, fact: Fact) -> Fact:
        """Guarda un fact. Si key+value ya existe, actualiza updated_at.
        Retorna el fact con id asignado."""

    def save_facts(self, facts: list[Fact]) -> int:
        """Guarda múltiples facts. Retorna cantidad guardados."""

    def get_all(self) -> list[Fact]:
        """Retorna todos los facts. Para v1, esto es suficiente."""

    def get_by_key(self, key: str) -> list[Fact]:
        """Retorna facts filtrados por key."""

    def delete(self, fact_id: int) -> bool:
        """Elimina un fact por id."""

    def delete_by_key(self, key: str) -> int:
        """Elimina todos los facts con una key. Retorna cantidad."""

    # === Lifecycle ===
    def init_db(self) -> None:
        """Crea la tabla si no existe."""

    def close(self) -> None:
        """Cierra la conexión."""
```

### MemoryManager

```python
class MemoryManager:
    """Orquesta extracción, almacenamiento y recuperación de memorias."""

    def __init__(self, store: MemoryStore, llm: LLMClient): ...

    # === Recuperación ===
    def load_all(self) -> list[Fact]:
        """Carga todos los facts de SQLite."""

    def format_for_prompt(self, facts: list[Fact]) -> str:
        """Formatea facts como bloque para inyectar en system prompt.
        Retorna string vacío si no hay facts."""

    # === Creación: Automática ===
    async def extract_from_conversation(
        self, messages: list[Message]
    ) -> list[Fact]:
        """Pasa la conversación al LLM y extrae facts nuevos.
        Llamado al cerrar sesión."""

    # === Creación: Explícita ===
    def remember(self, text: str) -> Fact:
        """Guarda un fact explícito desde comando del usuario.
        Parsea 'key: value' o usa 'nota' como key default."""

    # === Mantenimiento ===
    def forget(self, key: str) -> int:
        """Elimina facts por key. Retorna cantidad eliminados."""
```

## Extracción Automática

Al cerrar sesión, el `MemoryManager` pasa la conversación al LLM con
un prompt de extracción:

```python
EXTRACTION_PROMPT = """Analiza esta conversación y extrae hechos estables
sobre el usuario que valga la pena recordar para futuras conversaciones.

Retorna SOLO JSON válido:
{
  "facts": [
    {"key": "<categoría>", "value": "<hecho en tercera persona>"},
    ...
  ]
}

Reglas:
- Solo hechos ESTABLES (no estados temporales como "está cansado")
- Values en TERCERA PERSONA ("trabaja en Google", no "trabajo en Google")
- Keys descriptivas y en español: nombre, trabajo, ubicacion, hobby,
  proyecto, preferencia, tecnologia, idioma, etc.
- NO hay lista fija de keys — usá la que mejor describa el hecho
- Si no hay hechos nuevos, retorna {"facts": []}
- No extraigas preguntas ni hipótesis como hechos

Ejemplos de keys válidas:
  nombre, edad, trabajo, ubicacion, hobby, mascota, familia,
  proyecto_actual, stack_tecnologico, preferencia_editor,
  idioma, zona_horaria, objetivo, rutina, ...
"""
```

**Cuándo se ejecuta**: al cerrar sesión (CLI: al salir, Telegram: tras N
minutos de inactividad o explícitamente).

**Costo**: una llamada LLM extra por sesión. Con Groq/Llama 3.1 son ~2-3
segundos. Aceptable al cierre, no bloquea al usuario.

## Extracción Explícita

El usuario puede decir "recordá que prefiero TypeScript" en cualquier
momento. Rumi lo parsea y guarda inmediatamente:

```python
# El LLM detecta intención de "recordar" y llama al tool
class RememberTool(Tool):
    """Tool para guardar memorias explícitas."""

    name = "remember"
    description = "Save a fact about the user for future reference"

    parameters = {
        "type": "object",
        "properties": {
            "key": {
                "type": "string",
                "description": "Category (e.g. 'preferencia', 'proyecto')"
            },
            "value": {
                "type": "string",
                "description": "The fact to remember, in third person"
            }
        },
        "required": ["key", "value"]
    }

    async def execute(self, key: str, value: str, **kw) -> ToolResult:
        fact = Fact(key=key, value=value, source="explicit")
        self.memory_manager.store.save_fact(fact)
        return ToolResult(success=True, output=f"Recordado: {key} → {value}")
```

También un `ForgetTool` para eliminar:

```python
class ForgetTool(Tool):
    name = "forget"
    description = "Remove stored facts about the user by category"
    # ...
```

## Inyección en Prompt

Al inicio de cada conversación, `MemoryManager.format_for_prompt()`
genera un bloque que se inyecta en el system prompt:

```xml
<memory>
Lo que sabés del usuario:
- nombre: Lucas
- trabajo: desarrollador en una startup de fintech
- ubicacion: Buenos Aires
- stack_tecnologico: Python, TypeScript, PostgreSQL
- proyecto_actual: construyendo un agente personal llamado Rumi
- preferencia_editor: Neovim
- mascota: tiene un gato llamado Michi
</memory>
```

Si no hay facts, el bloque no se incluye (zero overhead en tokens).

### Impacto en tokens

| Facts guardados | Tokens aprox. | Impacto |
|----------------|---------------|---------|
| 0              | 0             | Ninguno |
| 10             | ~100          | Mínimo  |
| 50             | ~500          | Aceptable |
| 100            | ~1,000        | Límite razonable para cargar todo |
| 500+           | ~5,000        | Necesita filtrado/búsqueda |

Para v1, cargar todo es viable hasta ~100 facts. Cuando supere eso,
agregar FTS5 o filtrado por relevancia.

## Integración con AgentLoop

### Cambios al AgentLoop

```python
class AgentLoop:
    def __init__(
        self,
        tools: ToolRegistry,
        memory: MemoryManager | None = None,  # NUEVO
        ...
    ): ...

    async def _build_system_prompt(self) -> str:
        """Construye el system prompt con tools + skills + memory."""
        parts = [BASE_SYSTEM_PROMPT]

        # Tools
        parts.append(self.tools.get_schemas_prompt())

        # Skills (si están disponibles)
        if self.skill_manager:
            parts.append(self.skill_manager.get_available_skills_prompt())

        # Memory (NUEVO)
        if self.memory:
            facts = self.memory.load_all()
            memory_block = self.memory.format_for_prompt(facts)
            if memory_block:
                parts.append(memory_block)

        return "\n\n".join(parts)

    async def on_session_end(self, messages: list[Message]) -> None:
        """Hook al cerrar sesión. Extrae memorias automáticamente."""
        if self.memory:
            new_facts = await self.memory.extract_from_conversation(messages)
            if new_facts:
                self.memory.store.save_facts(new_facts)
```

### Registro de Tools

```python
# En el bootstrap (cli.py / bot.py)
memory_store = MemoryStore(db_path=Path.home() / ".rumi" / "memory.db")
memory_store.init_db()
memory_manager = MemoryManager(store=memory_store, llm=llm_client)

# Registrar tools de memoria
registry.register(RememberTool(memory_manager))
registry.register(ForgetTool(memory_manager))

# Pasar al AgentLoop
agent = AgentLoop(tools=registry, memory=memory_manager, ...)
```

## Estructura del Módulo

```
src/rumi/
├── memory/                   # NUEVO
│   ├── __init__.py           # Exports: MemoryManager, MemoryStore, Fact
│   ├── models.py             # Fact dataclass
│   ├── store.py              # MemoryStore (SQLite)
│   ├── manager.py            # MemoryManager (orquestación)
│   ├── extractor.py          # Prompt de extracción + parsing de respuesta LLM
│   └── tools.py              # RememberTool, ForgetTool
│
├── agent/                    # EXISTENTE — modificar
│   └── loop.py               # + memory param, + _build_system_prompt, + on_session_end
│
├── tools/                    # EXISTENTE — sin cambios
├── skills/                   # FUTURO
├── sandbox/                  # EXISTENTE — sin cambios
└── session/                  # EXISTENTE — sin cambios
```

## Deduplicación

El constraint `UNIQUE(key, value)` previene duplicados exactos. Pero el
LLM puede generar variaciones: "trabaja en Google" vs "es empleado de Google".

Para v1, no hacemos deduplicación semántica. Si se acumulan variaciones,
el usuario puede limpiar con "olvidate de mi trabajo" + "recordá que
trabajo en Google". En v2, se puede agregar normalización como la que
tenía Personality Lab.

## Fases de Implementación

### Fase 1: Core mínimo (storage + inyección)
- [ ] `models.py` — Fact dataclass
- [ ] `store.py` — MemoryStore con SQLite (CRUD + init_db)
- [ ] `manager.py` — MemoryManager (load_all, format_for_prompt)
- [ ] Modificar `loop.py` — inyectar memory block en system prompt
- [ ] Tests: store CRUD, format_for_prompt, dedup

### Fase 2: Creación de memorias
- [ ] `extractor.py` — Prompt de extracción + parser JSON
- [ ] `manager.py` — extract_from_conversation()
- [ ] `tools.py` — RememberTool, ForgetTool
- [ ] Hook on_session_end en AgentLoop
- [ ] Registrar tools en cli.py y bot.py
- [ ] Tests: extracción, tools, end-to-end

### Fase 3: Mejoras (cuando sea necesario)
- [ ] FTS5 para búsqueda cuando facts > 100
- [ ] Deduplicación semántica (normalización de values)
- [ ] Expiración de facts viejos no accedidos
- [ ] CLI: `rumi memory list|forget|export`

---

## Decisiones de Arquitectura

### ADR-030: SQLite como storage de memoria

**Status**: Aceptado

**Decisión**: Usar SQLite local en vez de Supabase para almacenar facts.

**Rationale**:
- Zero dependencias externas (SQLite viene con Python)
- Un solo archivo portable (`~/.rumi/memory.db`)
- Suficiente para un agente single-user
- FTS5 disponible si se necesita búsqueda
- Experiencia con Supabase en Personality Lab mostró complejidad innecesaria

**Consecuencias**:
- No hay sync entre dispositivos (aceptable para v1)
- Backup es copiar un archivo

### ADR-031: Keys flexibles sin whitelist

**Status**: Aceptado

**Decisión**: No restringir las keys de facts a una lista fija. El LLM
decide qué key usar según el contexto.

**Rationale**:
- La whitelist de Personality Lab (13 keys) era demasiado rígida
- Hechos como "proyecto_actual", "stack_tecnologico", "zona_horaria"
  no encajaban en ninguna categoría
- El LLM es suficientemente bueno para generar keys coherentes
- El prompt de extracción da ejemplos que guían sin restringir

**Consecuencias**:
- Puede haber inconsistencia entre keys ("trabajo" vs "empleo")
- Aceptable para v1; se puede agregar normalización después
- El usuario puede limpiar con forget + remember

### ADR-032: Extracción al cerrar sesión, no por turno

**Status**: Aceptado

**Decisión**: Extraer memorias una vez al cerrar la sesión, no después
de cada mensaje.

**Rationale**:
- Personality Lab extraía por turno (si CERT ≥ 3): costoso y ruidoso
- Una extracción al final ve la conversación completa → mejor contexto
- Una sola llamada LLM extra por sesión vs potencialmente N
- No agrega latencia durante la conversación

**Consecuencias**:
- Si el proceso se mata sin cerrar sesión, se pierden memorias de esa sesión
- Aceptable: graceful shutdown mitiga, y las memorias explícitas se guardan inmediato

### ADR-033: Solo facts, sin episodes

**Status**: Aceptado

**Decisión**: El sistema de memoria solo almacena facts (key-value).
No hay episodes ni memoria emocional.

**Rationale**:
- Episodes en Personality Lab se acumulaban sin utilidad real
- Rumi es un agente de productividad, no un companion emocional
- Facts cubren los tres tipos de memoria requeridos:
  - Hechos sobre el usuario: key=nombre, valor=Lucas
  - Historial de tareas: key=tarea_completada, valor=migró DB a PostgreSQL
  - Conocimiento: key=concepto, valor=asyncio.Queue es thread-safe en el event loop
- Simplicidad > completitud para v1

**Consecuencias**:
- No hay "memoria narrativa" — Rumi no recuerda *cómo* aprendió algo
- Si se necesita en el futuro, se puede agregar una tabla separada

### ADR-034: Cargar todos los facts en cada conversación

**Status**: Aceptado

**Decisión**: En v1, `load_all()` carga todos los facts y los inyecta
en el system prompt. Sin filtrado ni búsqueda.

**Rationale**:
- Simple de implementar (un SELECT)
- Viable hasta ~100 facts (~1,000 tokens)
- Para un agente personal, 100 facts cubre mucho
- Optimizar prematuramente agrega complejidad sin beneficio

**Consecuencias**:
- Si supera 100 facts, necesita FTS5 o filtrado (Fase 3)
- El prompt crece linealmente con los facts
