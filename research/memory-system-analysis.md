# Análisis del Sistema de Memoria de Rumi

## Resumen Ejecutivo

Rumi implementa un sistema de memoria basado en **sesiones persistentes** con tres responsabilidades principales:

1. **Persistencia**: Guardar/cargar estado de conversación en disco
2. **Concurrencia**: Locks para evitar procesamiento simultáneo por sesión
3. **Lifecycle**: TTL y limpieza automática de sesiones expiradas

---

## Arquitectura

### Diagrama de Componentes

```
┌─────────────────────────────────────────────────────────────────────┐
│                           INTERFACES                                 │
│                                                                     │
│    ┌──────────────┐                      ┌──────────────────┐       │
│    │   CLI        │                      │   Telegram Bot   │       │
│    └──────┬───────┘                      └────────┬─────────┘       │
│           │                                       │                 │
│           └───────────────┬───────────────────────┘                 │
│                           │                                         │
│                           ▼                                         │
│    ┌────────────────────────────────────────────────────────┐       │
│    │                  SESSION MANAGER                        │       │
│    │                                                        │       │
│    │  ┌────────────────┐  ┌────────────────┐  ┌──────────┐ │       │
│    │  │ SessionState   │  │ Locks          │  │ Busy Set │ │       │
│    │  │ (in-memory)    │  │ (asyncio.Lock) │  │          │ │       │
│    │  └───────┬────────┘  └────────────────┘  └──────────┘ │       │
│    │          │                                             │       │
│    │          ▼                                             │       │
│    │  ┌────────────────────────────────────────────────────┐│       │
│    │  │         PERSISTENCIA EN DISCO                      ││       │
│    │  │  ~/.rumi/sessions/{chat_id}.json              ││       │
│    │  └────────────────────────────────────────────────────┘│       │
│    └────────────────────────────────────────────────────────┘       │
│                           │                                         │
│                           ▼                                         │
│    ┌────────────────────────────────────────────────────────┐       │
│    │                   AGENT LOOP                            │       │
│    │  Recibe history[] de SessionManager                     │       │
│    │  Lo inyecta entre system prompt y mensaje actual        │       │
│    └────────────────────────────────────────────────────────┘       │
└─────────────────────────────────────────────────────────────────────┘
```

### Flujo de Datos

```
Usuario envía mensaje
        │
        ▼
┌───────────────────────────┐
│  acquire(chat_id)         │ ◄── Si ya ocupado: retorna BUSY_MESSAGE
└───────────────────────────┘
        │
        ▼
┌───────────────────────────┐
│  add_message(user, msg)   │ ◄── Guarda en session.messages[]
└───────────────────────────┘
        │
        ▼
┌───────────────────────────┐
│  get_messages(for_llm)    │ ◄── Últimos 20, formato {role, content}
└───────────────────────────┘
        │
        ▼
┌───────────────────────────┐
│  AgentLoop.run(history)   │ ◄── Inyecta historial en conversación
└───────────────────────────┘
        │
        ▼
┌───────────────────────────┐
│  add_message(assistant)   │ ◄── Guarda respuesta
└───────────────────────────┘
        │
        ▼
┌───────────────────────────┐
│  release(chat_id)         │ ◄── Persiste a disco, libera lock
└───────────────────────────┘
```

---

## Estructuras de Datos

### SessionState

```python
@dataclass
class SessionState:
    chat_id: str                           # Identificador único de sesión
    created_at: float                      # Unix timestamp de creación
    last_activity: float                   # Unix timestamp de última actividad
    container_id: str | None               # ID de Docker container asociado
    messages: list[dict[str, Any]]         # Historial de mensajes
    context: dict[str, Any]                # Almacenamiento key-value libre
```

**Mensaje en el historial:**
```python
{
    "role": "user" | "assistant",
    "content": str,
    "timestamp": float  # Unix timestamp
}
```

### SessionConfig

```python
@dataclass
class SessionConfig:
    sessions_dir: Path      # Default: ~/.rumi/sessions/
    ttl_seconds: float      # Default: 3600 (1 hora)
    cleanup_interval: float # Default: 300 (5 minutos)
```

---

## Patrones de Diseño Identificados

### 1. Repository Pattern (Implícito)

`SessionManager` actúa como repositorio que abstrae la persistencia:

```python
# Operaciones CRUD sobre sesiones
session = manager.get_session(chat_id)    # Read (+ Create if not exists)
manager._save_session(session)             # Update
await manager.destroy_session(chat_id)     # Delete
```

### 2. Unit of Work (Simplificado)

El ciclo `acquire()` → operaciones → `release()` funciona como una transacción:

```python
acquired, _ = await manager.acquire(chat_id)
try:
    # Todas las modificaciones aquí
    manager.add_message(chat_id, "user", msg)
    # ... procesar ...
    manager.add_message(chat_id, "assistant", response)
finally:
    manager.release(chat_id)  # Persiste todos los cambios
```

### 3. Lazy Loading

Las sesiones se cargan de disco solo cuando se acceden:

```python
def get_session(self, chat_id: str) -> SessionState:
    if chat_id not in self._sessions:
        session = self._load_session(chat_id)  # Intenta cargar de disco
        if session is None:
            session = SessionState(chat_id=chat_id)  # Crea nueva
        self._sessions[chat_id] = session
    return self._sessions[chat_id]
```

### 4. Guard (Concurrencia)

Doble verificación para evitar race conditions:

```python
async def acquire(self, chat_id: str) -> tuple[bool, str | None]:
    if self.is_busy(chat_id):        # Check 1: busy set
        return False, BUSY_MESSAGE

    lock = self.get_lock(chat_id)
    if lock.locked():                 # Check 2: actual lock
        return False, BUSY_MESSAGE

    await lock.acquire()
    self._busy.add(chat_id)           # Mark as busy
    return True, None
```

### 5. Background Task Pattern

Limpieza periódica en un task asyncio:

```python
async def _cleanup_loop(self) -> None:
    while True:
        await asyncio.sleep(self.config.cleanup_interval)
        await self.cleanup_expired()
```

---

## Integración con AgentLoop

El `AgentLoop` recibe el historial como parámetro opcional:

```python
# bot.py:199-207
all_messages = self.sessions.get_messages(chat_id, limit=20, for_llm=True)
history = all_messages[:-1] or None  # Excluye mensaje actual

result = await agent.run(message, chat_id=chat_id, history=history)
```

El `AgentLoop` inyecta el historial entre el system prompt y el mensaje actual:

```python
# loop.py:95-102
messages = [
    {"role": "system", "content": build_system_prompt(...)},
]

if history:
    messages.extend(history)  # Historial de sesión aquí

messages.append({"role": "user", "content": message})  # Mensaje actual
```

---

## Análisis de Fortalezas

### 1. Simplicidad
- JSON plano en disco, fácil de inspeccionar y debuggear
- Dataclasses nativas de Python, sin ORM ni dependencias
- API clara: `get_session`, `add_message`, `get_messages`

### 2. Persistencia Eficiente
- Write-behind: solo persiste al hacer `release()`
- Read-through: carga de disco solo si no está en memoria
- Sin base de datos externa

### 3. Concurrencia Robusta
- Un lock por sesión (no global)
- Doble verificación (busy set + lock)
- Mensajes claros al usuario cuando está ocupado

### 4. Lifecycle Automático
- TTL configurable
- Background cleanup cada N minutos
- Destrucción limpia (memoria + disco + container)

### 5. Formato LLM-Ready
- `for_llm=True` retorna exactamente lo que espera Groq API
- Elimina timestamp y metadata innecesaria
- Limita a últimos N mensajes automáticamente

---

## Análisis de Debilidades y Limitaciones

### 1. No hay Compresión de Historial

**Problema**: Los mensajes crecen indefinidamente hasta el TTL.

```
Sesión de 1 hora, 200 mensajes → JSON de varios MB
Solo usamos últimos 20 → Desperdicio de almacenamiento
```

**Impacto**: Archivos JSON grandes, carga lenta.

### 2. Sin Búsqueda

**Problema**: Solo acceso secuencial a mensajes.

```python
# No existe:
manager.search_messages(chat_id, query="error docker")
```

**Impacto**: No se puede consultar historial por contenido.

### 3. Context No Estructurado

**Problema**: `context` es un dict genérico sin validación.

```python
# Cualquier cosa es válida
manager.set_context(chat_id, "foo", {"nested": {"arbitrario": True}})
```

**Impacto**: Difícil saber qué claves existen, no hay autocompletado.

### 4. No hay Memoria entre Sesiones

**Problema**: Cuando expira la sesión, se pierde todo.

```
Usuario: "siempre prefiero TypeScript"
[1 hora después, sesión expira]
Usuario: "crea un proyecto"
→ Agent no recuerda preferencia
```

**Impacto**: No hay aprendizaje a largo plazo.

### 5. Concurrencia Solo a Nivel Proceso

**Problema**: Los locks son `asyncio.Lock`, no funcionan entre procesos.

```
Proceso A: acquire("chat-123") ✓
Proceso B: acquire("chat-123") ✓  ← También adquiere, race condition!
```

**Impacto**: No escala horizontalmente.

### 6. Sin Encriptación

**Problema**: Los JSON se guardan en texto plano.

```bash
cat ~/.rumi/sessions/123.json
# Muestra todas las conversaciones del usuario
```

**Impacto**: Privacidad comprometida si el disco es accedido.

---

## Comparación con Otros Enfoques

| Aspecto | Rumi | LangChain Memory | ChatGPT |
|---------|----------|------------------|---------|
| Almacenamiento | JSON files | Pluggable (Redis, etc) | Cloud DB |
| Compresión | No | ConversationSummaryMemory | Automática |
| Búsqueda | No | VectorStoreRetrieverMemory | Embeddings |
| Multi-sesión | No | Sí | Sí |
| Persistencia | Por sesión | Configurable | Permanente |
| Complejidad | Baja | Media-Alta | Alta |

---

## Métricas Clave

| Métrica | Valor |
|---------|-------|
| Líneas de código | ~260 (manager.py) |
| Dependencias externas | 0 (solo stdlib) |
| Tests | 35+ casos en test_session.py |
| TTL default | 1 hora |
| Cleanup interval | 5 minutos |
| Max messages para LLM | 20 |

---

## Flujo de Ciclo de Vida Completo

```
                    ┌─────────────────┐
                    │   INICIO        │
                    │   (no session)  │
                    └────────┬────────┘
                             │
                    ┌────────▼────────┐
                    │   CREACIÓN      │
    Usuario envía   │   get_session() │
    primer mensaje  │   crea archivo  │
                    └────────┬────────┘
                             │
              ┌──────────────┴──────────────┐
              │                             │
     ┌────────▼────────┐           ┌────────▼────────┐
     │   ACTIVA        │◄─────────►│   BUSY          │
     │   (en memoria)  │  acquire/ │   (procesando)  │
     │                 │  release  │                 │
     └────────┬────────┘           └─────────────────┘
              │
              │ Sin actividad > TTL
              │ o /reset
              │
     ┌────────▼────────┐
     │   DESTRUIDA     │
     │   - borra JSON  │
     │   - borra lock  │
     │   - destruye    │
     │     container   │
     └─────────────────┘
```

---

## Código Clave Anotado

### Adquisición de Sesión (Concurrencia)

```python
async def acquire(self, chat_id: str) -> tuple[bool, str | None]:
    # GUARD 1: Verificación rápida sin bloqueo
    if self.is_busy(chat_id):
        return False, self.BUSY_MESSAGE

    lock = self.get_lock(chat_id)

    # GUARD 2: Verificación del lock real
    if lock.locked():
        return False, self.BUSY_MESSAGE

    # Adquirir lock (no bloqueante porque ya verificamos)
    await lock.acquire()

    # Marcar como ocupado (para verificación rápida)
    self._busy.add(chat_id)

    # Actualizar timestamp de actividad
    session = self.get_session(chat_id)
    session.touch()

    return True, None
```

### Formato para LLM

```python
def get_messages(self, chat_id: str, limit: int = 20, for_llm: bool = False):
    # Obtener últimos N mensajes
    messages = self.get_session(chat_id).messages[-limit:]

    if for_llm:
        # Solo role + content (lo que espera Groq API)
        return [{"role": m["role"], "content": m["content"]} for m in messages]

    # Con timestamp y toda la metadata
    return messages
```

### Destrucción de Sesión

```python
async def destroy_session(self, chat_id: str) -> None:
    # 1. Limpiar memoria
    if chat_id in self._sessions:
        del self._sessions[chat_id]

    # 2. Limpiar lock
    if chat_id in self._locks:
        del self._locks[chat_id]

    # 3. Limpiar busy set
    self._busy.discard(chat_id)

    # 4. Borrar archivo de disco
    self._delete_session_file(chat_id)

    # 5. Destruir container Docker asociado
    if self.sandbox:
        self.sandbox.destroy_container(chat_id)
```

---

## Conclusiones

El sistema de memoria de Rumi es **pragmático y efectivo** para su caso de uso:

1. **Suficiente para un asistente personal**: No necesita escalar a millones de usuarios
2. **Fácil de debuggear**: JSON plano, sin magia
3. **Seguro por diseño**: Un lock por sesión, limpieza automática
4. **Integración limpia**: El AgentLoop recibe historial como parámetro inyectable

Las limitaciones (sin compresión, sin búsqueda, sin persistencia entre sesiones) son **trade-offs aceptables** para mantener la simplicidad. Si el proyecto crece, las secciones de "Mejoras Propuestas" en `docs/memory-system.md` ofrecen un roadmap claro.
