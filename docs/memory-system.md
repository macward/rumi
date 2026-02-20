# Sistema de Memoria de Rumi

## Descripción General

Rumi implementa un sistema de memoria de dos capas:

1. **Session Memory** (temporal): Historial de conversación y contexto por chat
2. **Facts Memory** (persistente): Hechos estables sobre el usuario que sobreviven entre sesiones

---

# Parte 1: Facts Memory (Memoria Persistente)

El sistema de Facts almacena información estable sobre el usuario que se mantiene entre sesiones.

## Arquitectura

```
┌─────────────────────────────────────────────────────────────────────┐
│                         FACTS MEMORY                                 │
│                                                                      │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │                     MemoryManager                              │  │
│  │  - load_all(): Cargar todos los facts                         │  │
│  │  - format_for_prompt(): Generar bloque <memory>               │  │
│  │  - extract_from_conversation(): Extracción automática         │  │
│  └───────────────────────────────────────────────────────────────┘  │
│                              │                                       │
│              ┌───────────────┼───────────────┐                       │
│              ▼               ▼               ▼                       │
│  ┌──────────────────┐ ┌──────────────────┐ ┌──────────────────────┐ │
│  │   MemoryStore    │ │  FactExtractor   │ │ RememberTool/        │ │
│  │   (SQLite)       │ │  (LLM-based)     │ │ ForgetTool           │ │
│  └──────────────────┘ └──────────────────┘ └──────────────────────┘ │
│           │                                                          │
│           ▼                                                          │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │              ~/.rumi/memory.db (SQLite)                    │  │
│  └───────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

## Modelo de Datos: Fact

```python
@dataclass(frozen=True)
class Fact:
    key: str          # Categoría: 'nombre', 'trabajo', 'preferencia'...
    value: str        # El hecho en tercera persona
    id: int | None    # ID en la base de datos
    source: str       # 'auto' (extraído) o 'explicit' (usuario)
    created_at: str   # ISO timestamp
    updated_at: str   # ISO timestamp
```

## Componentes

### MemoryStore (SQLite)

Almacenamiento persistente con deduplicación por `(key, value)`.

```sql
CREATE TABLE facts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    key         TEXT NOT NULL,
    value       TEXT NOT NULL,
    source      TEXT NOT NULL DEFAULT 'auto',
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(key, value)
)
```

**Operaciones:**
```python
store = MemoryStore(Path("~/.rumi/memory.db"))
store.init_db()

# Guardar (upsert por key+value)
fact = store.save_fact(Fact(key="trabajo", value="trabaja en Google"))

# Consultar
all_facts = store.get_all()
work_facts = store.get_by_key("trabajo")

# Eliminar
store.delete(fact_id=1)
store.delete_by_key("trabajo")  # Todos los facts de esa categoría
```

### FactExtractor (Extracción automática)

Usa el LLM para extraer hechos estables de las conversaciones al finalizar la sesión.

```python
extractor = FactExtractor(
    llm_client=AsyncGroq(),
    model="llama-3.1-70b-versatile"
)

facts = await extractor.extract(messages)
# → [Fact(key="proyecto", value="está trabajando en Rumi"), ...]
```

**Criterios de extracción:**
- Solo hechos **estables** (no estados temporales como "está cansado")
- Valores en **tercera persona** ("trabaja en Google", no "trabajo en")
- Keys descriptivas en español: `nombre`, `trabajo`, `ubicacion`, `hobby`, `proyecto`, `preferencia`, `tecnologia`...

### RememberTool y ForgetTool

Herramientas para que el usuario gestione su memoria explícitamente.

```python
# remember(key="nombre", value="se llama Juan")
remember_tool = RememberTool(store)
result = await remember_tool.execute(key="nombre", value="se llama Juan")
# → "Recordado: nombre → se llama Juan"

# forget(key="trabajo")
forget_tool = ForgetTool(store)
result = await forget_tool.execute(key="trabajo")
# → "Olvidado: 2 hechos sobre 'trabajo'"
```

### MemoryManager

Orquestador central que coordina todos los componentes.

```python
manager = MemoryManager(store=store, extractor=extractor)

# Cargar facts para el prompt
facts = manager.load_all()
prompt_block = manager.format_for_prompt(facts)
# → "<memory>\nLo que sabés del usuario:\n- nombre: se llama Juan\n- trabajo: trabaja en Google\n</memory>"

# Extracción al final de sesión
new_facts = await manager.extract_from_conversation(messages)
```

## Integración con el Sistema

### Inyección en System Prompt

Los facts se inyectan en el prompt del agente:

```xml
<memory>
Lo que sabés del usuario:
- nombre: se llama Juan
- trabajo: trabaja en Google
- preferencia: prefiere TypeScript
</memory>
```

### Hook on_session_end

Al finalizar una sesión, se extraen automáticamente facts nuevos:

```python
# En SessionManager
async def on_session_end(self, chat_id: str):
    messages = self.get_messages(chat_id)
    await memory_manager.extract_from_conversation(messages)
```

---

# Parte 2: Session Memory (Memoria de Sesión)

Rumi implementa un sistema de memoria basado en **sesiones persistentes** que mantiene el estado de cada conversación (chat) entre interacciones. El sistema está implementado en `SessionManager` y almacena:

- Historial de mensajes
- Contexto key-value arbitrario
- Metadata de sesión (timestamps, container_id)

## Arquitectura

```
┌─────────────────────────────────────────────────────────────────┐
│                         TELEGRAM / CLI                          │
│                              │                                  │
│                              ▼                                  │
│  ┌───────────────────────────────────────────────────────────┐ │
│  │                    SessionManager                         │ │
│  │                                                           │ │
│  │   ┌─────────────┐    ┌─────────────┐    ┌─────────────┐  │ │
│  │   │  Session A  │    │  Session B  │    │  Session C  │  │ │
│  │   │  (chat_id)  │    │  (chat_id)  │    │  (chat_id)  │  │ │
│  │   └──────┬──────┘    └──────┬──────┘    └──────┬──────┘  │ │
│  │          │                  │                  │         │ │
│  │          ▼                  ▼                  ▼         │ │
│  │   ┌─────────────────────────────────────────────────────┐│ │
│  │   │              ~/.rumi/sessions/                  ││ │
│  │   │   chat_123.json   chat_456.json   chat_789.json    ││ │
│  │   └─────────────────────────────────────────────────────┘│ │
│  └───────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

## Componentes

### SessionState

Estructura de datos que representa una sesión:

```python
@dataclass
class SessionState:
    chat_id: str                           # Identificador único
    created_at: float                      # Timestamp de creación
    last_activity: float                   # Última actividad
    container_id: str | None               # ID del container Docker asociado
    messages: list[dict[str, Any]]         # Historial de mensajes
    context: dict[str, Any]                # Contexto key-value
```

### SessionConfig

Configuración del sistema:

```python
@dataclass
class SessionConfig:
    sessions_dir: Path      # ~/.rumi/sessions/
    ttl_seconds: float      # 3600 (1 hora)
    cleanup_interval: float # 300 (5 minutos)
```

## Almacenamiento

### Ubicación
```
~/.rumi/sessions/{chat_id}.json
```

### Formato del archivo
```json
{
  "chat_id": "user_12345",
  "created_at": 1707700000.0,
  "last_activity": 1707703600.0,
  "container_id": "abc123def456",
  "messages": [
    {
      "role": "user",
      "content": "lista los archivos",
      "timestamp": 1707700100.0
    },
    {
      "role": "assistant",
      "content": "Aquí están los archivos...",
      "timestamp": 1707700105.0
    }
  ],
  "context": {
    "working_dir": "/workspace/project",
    "last_command": "ls -la"
  }
}
```

## Operaciones Principales

### 1. Obtener/Crear Sesión

```python
session = manager.get_session(chat_id)
# Si no existe en memoria, intenta cargar de disco
# Si no existe en disco, crea una nueva
```

### 2. Concurrencia (Locks)

```python
acquired, error = await manager.acquire(chat_id)
if not acquired:
    return error  # "⏳ Ya estoy trabajando..."
try:
    # Procesar mensaje
finally:
    manager.release(chat_id)
```

### 3. Historial de Mensajes

```python
# Agregar mensaje
manager.add_message(chat_id, role="user", content="hola")

# Obtener últimos 20 mensajes
messages = manager.get_messages(chat_id, limit=20)

# Formato para LLM (solo role + content)
llm_messages = manager.get_messages(chat_id, for_llm=True)
```

### 4. Contexto Key-Value

```python
# Guardar contexto
manager.set_context(chat_id, "last_file", "/workspace/readme.md")

# Recuperar contexto
last_file = manager.get_context(chat_id, "last_file", default=None)
```

### 5. Destruir Sesión

```python
await manager.destroy_session(chat_id)
# - Elimina de memoria
# - Elimina archivo de disco
# - Destruye container Docker asociado
```

### 6. Limpieza Automática

```python
# Ejecuta cada 5 minutos en background
# Elimina sesiones con last_activity > 1 hora
await manager.cleanup_expired()
```

## Flujo de Vida de una Sesión

```
┌─────────────────────────────────────────────────────────────────┐
│ 1. CREACIÓN                                                     │
│    Usuario envía primer mensaje                                 │
│    → get_session() crea SessionState nuevo                      │
│    → Archivo JSON creado en disco                               │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ 2. USO ACTIVO                                                   │
│    Cada mensaje:                                                │
│    → acquire() bloquea sesión                                   │
│    → add_message() guarda en historial                          │
│    → AgentLoop usa get_messages(for_llm=True)                   │
│    → release() desbloquea y persiste a disco                    │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ 3. EXPIRACIÓN                                                   │
│    Si last_activity > 1 hora:                                   │
│    → cleanup_expired() detecta sesión inactiva                  │
│    → destroy_session() elimina todo                             │
│                                                                 │
│    O si usuario ejecuta /reset:                                 │
│    → destroy_session() elimina todo                             │
└─────────────────────────────────────────────────────────────────┘
```

## Integración con Otros Componentes

### Con AgentLoop

```python
# El AgentLoop recibe historial de la sesión
history = session_manager.get_messages(chat_id, limit=20, for_llm=True)
result = await agent.run(message, chat_id=chat_id, history=history)
```

### Con SandboxManager

```python
# SessionManager tiene referencia al sandbox
# Al destruir sesión, destruye el container asociado
async def destroy_session(self, chat_id: str):
    ...
    if self.sandbox:
        self.sandbox.destroy_container(chat_id)
```

### Con Telegram Bot

```python
# El bot usa acquire/release para control de concurrencia
acquired, error = await session_manager.acquire(chat_id)
if not acquired:
    await update.message.reply_text(error)
    return
```

---

# Notas de Mejora

## 1. Compresión de Historial

**Problema actual**: El historial crece indefinidamente hasta que expira la sesión.

**Mejora propuesta**:
- Resumir mensajes antiguos con el LLM
- Mantener últimos N mensajes completos + resumen de anteriores
- Ventana deslizante con compresión

```python
class SessionState:
    messages: list[dict]      # Últimos 20 mensajes
    summary: str | None       # Resumen de mensajes anteriores
```

## 2. Memoria Semántica

**Problema actual**: Solo se guarda texto plano de mensajes.

**Mejora propuesta**:
- Extraer "hechos" de las conversaciones
- Almacenar entidades mencionadas (archivos, comandos, errores)
- Índice semántico para búsqueda

```python
class SessionState:
    facts: list[str]          # ["usuario prefiere Python", "proyecto usa Docker"]
    entities: dict[str, Any]  # {"files": [...], "errors": [...]}
```

## 3. Memoria Persistente entre Sesiones

**Problema actual**: Cada sesión es independiente, se pierde todo al expirar.

**Mejora propuesta**:
- Archivo de perfil de usuario separado
- Preferencias que sobreviven a sesiones
- Historial de comandos frecuentes

```
~/.rumi/
├── sessions/         # Sesiones temporales
│   └── chat_123.json
└── profiles/         # Perfiles persistentes
    └── user_123.json
```

## 4. Importar/Exportar Sesión

**Problema actual**: No hay forma de guardar/restaurar una sesión manualmente.

**Mejora propuesta**:
- Comando `/export` para descargar sesión
- Comando `/import` para restaurar sesión anterior
- Útil para compartir contexto o retomar trabajo

## 5. Límites de Almacenamiento

**Problema actual**: Sin límites explícitos de tamaño.

**Mejora propuesta**:
- Límite de mensajes por sesión (ej: 1000)
- Límite de tamaño de archivo (ej: 1MB)
- Política de truncado cuando se excede

```python
MAX_MESSAGES = 1000
MAX_FILE_SIZE = 1_000_000  # 1MB
```

## 6. Encriptación

**Problema actual**: Sesiones guardadas en texto plano.

**Mejora propuesta**:
- Encriptar archivos de sesión en disco
- Clave derivada de variable de entorno
- Proteger datos sensibles del usuario

## 7. Contexto Estructurado

**Problema actual**: `context` es un dict genérico sin schema.

**Mejora propuesta**:
- Definir tipos de contexto esperados
- Validación de valores
- Documentación de claves conocidas

```python
class SessionContext:
    working_dir: str | None
    last_command: str | None
    environment: dict[str, str]
    file_cache: dict[str, str]
```

## 8. Eventos de Sesión

**Problema actual**: No hay hooks para eventos de ciclo de vida.

**Mejora propuesta**:
- Callback on_session_created
- Callback on_session_expired
- Callback on_message_added
- Útil para logging, analytics, notificaciones

## 9. Sesiones Multi-Dispositivo

**Problema actual**: Una sesión por chat_id, sin soporte multi-cliente.

**Mejora propuesta**:
- Sincronización si el usuario usa múltiples clientes
- Conflicto de locks más sofisticado
- Estado compartido entre instancias

## 10. Búsqueda en Historial

**Problema actual**: Solo acceso secuencial a mensajes.

**Mejora propuesta**:
- Comando `/search <término>` para buscar en historial
- Índice invertido sobre contenido de mensajes
- Filtros por fecha, rol, tipo de contenido
