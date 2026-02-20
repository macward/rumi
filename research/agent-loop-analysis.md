# Análisis del AgentLoop de Rumi

## Resumen Ejecutivo

El `AgentLoop` es el núcleo de Rumi: implementa el patrón **ReAct (Reasoning + Acting)** donde un LLM razona sobre qué hacer, ejecuta herramientas, y observa los resultados en un ciclo iterativo.

**Características principales:**
- Ciclo Think → Act → Observe
- 3 circuit breakers para prevenir loops infinitos
- Inyección de historial de conversación
- Integración con Groq API para LLM
- Dispatch de herramientas vía ToolRegistry

---

## Arquitectura

### Diagrama de Componentes

```
┌─────────────────────────────────────────────────────────────────────────┐
│                            AGENT LOOP                                    │
│                                                                         │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                        ENTRADA                                   │   │
│  │                                                                  │   │
│  │   message: str          El mensaje actual del usuario           │   │
│  │   chat_id: str | None   Identificador de sesión (opcional)      │   │
│  │   history: list | None  Historial de conversación               │   │
│  │                                                                  │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                    │                                    │
│                                    ▼                                    │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                     CONSTRUCCIÓN DE MENSAJES                     │   │
│  │                                                                  │   │
│  │   [0] system      →  Prompt base + descripción de tools         │   │
│  │   [1..n] history  →  Historial inyectado (si existe)            │   │
│  │   [n+1] user      →  Mensaje actual                             │   │
│  │                                                                  │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                    │                                    │
│                                    ▼                                    │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                         CICLO PRINCIPAL                          │   │
│  │                                                                  │   │
│  │   for turn in range(max_turns):                                 │   │
│  │                                                                  │   │
│  │      ┌──────────────────────────────────────────────────────┐   │   │
│  │      │  THINK                                                │   │   │
│  │      │  LLM decide: responder o llamar herramienta           │   │   │
│  │      └──────────────────────────────────────────────────────┘   │   │
│  │                           │                                      │   │
│  │           ┌───────────────┴───────────────┐                     │   │
│  │           │                               │                      │   │
│  │     tool_calls?                      no tool_calls              │   │
│  │           │                               │                      │   │
│  │           ▼                               ▼                      │   │
│  │      ┌──────────┐                   ┌──────────┐                │   │
│  │      │   ACT    │                   │  RETURN  │                │   │
│  │      │ ejecutar │                   │ response │                │   │
│  │      │  tools   │                   │          │                │   │
│  │      └────┬─────┘                   └──────────┘                │   │
│  │           │                                                      │   │
│  │           ▼                                                      │   │
│  │      ┌──────────┐                                               │   │
│  │      │ OBSERVE  │                                               │   │
│  │      │ agregar  │                                               │   │
│  │      │ resultado│                                               │   │
│  │      └────┬─────┘                                               │   │
│  │           │                                                      │   │
│  │           └──────────────→ siguiente turno                      │   │
│  │                                                                  │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                    │                                    │
│                                    ▼                                    │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                           SALIDA                                 │   │
│  │                                                                  │   │
│  │   AgentResult:                                                   │   │
│  │     response: str           Texto final del LLM                 │   │
│  │     stop_reason: StopReason Por qué terminó                     │   │
│  │     turns: int              Cuántos turnos usó                  │   │
│  │     tool_calls: list        Log de todas las llamadas           │   │
│  │                                                                  │   │
│  └─────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────┘
```

### Dependencias

```
AgentLoop
    │
    ├── ToolRegistry ────────→ dispatch(name, args) → ToolResult
    │       │
    │       └── Tool (bash, web_fetch)
    │               │
    │               └── execute(**kwargs) → ToolResult
    │
    ├── AsyncGroq ───────────→ chat.completions.create()
    │
    └── prompt.py ───────────→ build_system_prompt()
                               format_tool_result()
```

---

## El Ciclo ReAct

### Think (Pensar)

El LLM recibe el contexto completo y decide qué hacer:

```python
response = await self.client.chat.completions.create(
    model=self.config.model,
    messages=messages,
    tools=self.registry.get_tools_schema() or None,
    tool_choice="auto"  # LLM decide si usar tools
)
```

**Salidas posibles:**
1. `tool_calls` no vacío → El LLM quiere ejecutar herramientas
2. `content` sin `tool_calls` → El LLM terminó, responde al usuario

### Act (Actuar)

Si el LLM solicita herramientas, se ejecutan:

```python
for tool_call in assistant_message.tool_calls:
    tool_name = tool_call.function.name
    tool_args = json.loads(tool_call.function.arguments)

    # Dispatch a través del registry
    result = await self.registry.dispatch(tool_name, tool_args)
```

**El dispatch incluye:**
1. Validación del nombre de herramienta
2. Validación de argumentos contra el schema JSON
3. Ejecución con manejo de excepciones
4. Retorno de `ToolResult`

### Observe (Observar)

El resultado se formatea y agrega a la conversación:

```python
tool_response = format_tool_result(
    tool_name, result.success, result.output, result.error
)

messages.append({
    "role": "tool",
    "tool_call_id": tool_call.id,
    "content": tool_response,
})
```

**Formato del resultado:**
```
[bash] Success:
total 8
drwxr-xr-x  2 user user 4096 Jan 15 10:00 .
-rw-r--r--  1 user user  123 Jan 15 10:00 file.txt
```

O en caso de error:
```
[bash] Error: Command not allowed: rm -rf /
```

---

## Circuit Breakers

Rumi implementa 3 mecanismos de protección para evitar loops infinitos:

### 1. Max Turns

```python
for turn in range(self.config.max_turns):  # Default: 10
    ...

# Si se agotan los turnos
return AgentResult(
    response="Max turns reached",
    stop_reason=StopReason.MAX_TURNS,
    ...
)
```

**Propósito:** Límite duro absoluto, independiente del comportamiento.

### 2. Repeated Calls

```python
def _check_repeated_call(self, tool_call: dict) -> bool:
    call_sig = json.dumps(tool_call, sort_keys=True)

    if call_sig == self._last_tool_call:
        self._repeated_count += 1
        return self._repeated_count >= self.config.max_repeated_calls  # Default: 2

    self._last_tool_call = call_sig
    self._repeated_count = 1
    return False
```

**Propósito:** Detectar cuando el LLM entra en loop llamando la misma herramienta con los mismos argumentos.

**Ejemplo de detección:**
```
Turn 1: bash({"command": "ls"})
Turn 2: bash({"command": "ls"})  ← STOP: repeated_call
```

### 3. Consecutive Errors

```python
if not result.success:
    self._consecutive_errors += 1
    if self._consecutive_errors >= self.config.max_consecutive_errors:  # Default: 3
        return AgentResult(
            response=f"Stopped: {n} consecutive errors",
            stop_reason=StopReason.CONSECUTIVE_ERRORS,
            ...
        )
else:
    self._consecutive_errors = 0  # Reset on success
```

**Propósito:** Evitar que el LLM siga intentando una estrategia que falla repetidamente.

### Diagrama de Circuit Breakers

```
                    ┌─────────────────┐
                    │  Ejecutar Tool  │
                    └────────┬────────┘
                             │
              ┌──────────────┼──────────────┐
              │              │              │
              ▼              ▼              ▼
      ┌──────────────┐ ┌──────────┐ ┌──────────────┐
      │ ¿Repetido?   │ │ ¿Error?  │ │ ¿Max turns?  │
      │ (same args)  │ │          │ │              │
      └──────┬───────┘ └────┬─────┘ └──────┬───────┘
             │              │              │
      ┌──────┴──────┐ ┌─────┴─────┐ ┌──────┴──────┐
      │ count >= 2  │ │ count >= 3│ │ turn >= 10  │
      └──────┬──────┘ └─────┬─────┘ └──────┬──────┘
             │              │              │
             ▼              ▼              ▼
      ┌──────────────────────────────────────────┐
      │              STOP LOOP                   │
      │  return AgentResult(stop_reason=...)     │
      └──────────────────────────────────────────┘
```

---

## Inyección de Historial

El AgentLoop soporta historial de conversación para contexto multi-turno:

```python
async def run(
    self,
    message: str,
    chat_id: str | None = None,
    history: list[dict[str, Any]] | None = None,  # ← Historial opcional
) -> AgentResult:
```

### Construcción de Mensajes

```python
messages = [
    {"role": "system", "content": build_system_prompt(...)},
]

if history:
    messages.extend(history)  # Historial inyectado

messages.append({"role": "user", "content": message})  # Mensaje actual
```

### Ejemplo de Mensajes Resultantes

```python
# Sin historial:
[
    {"role": "system", "content": "You are Rumi..."},
    {"role": "user", "content": "ls /workspace"}
]

# Con historial:
[
    {"role": "system", "content": "You are Rumi..."},
    {"role": "user", "content": "My name is Alice"},           # history[0]
    {"role": "assistant", "content": "Nice to meet you!"},     # history[1]
    {"role": "user", "content": "What's 2+2?"},                # history[2]
    {"role": "assistant", "content": "4"},                     # history[3]
    {"role": "user", "content": "Do you remember my name?"}    # mensaje actual
]
```

---

## Estructuras de Datos

### AgentConfig

```python
@dataclass
class AgentConfig:
    model: str = "llama-3.1-70b-versatile"
    max_turns: int = 10
    max_consecutive_errors: int = 3
    max_repeated_calls: int = 2
```

### AgentResult

```python
@dataclass
class AgentResult:
    response: str                              # Texto final
    stop_reason: StopReason                    # Por qué terminó
    turns: int                                 # Cuántos turnos usó
    tool_calls: list[dict[str, Any]] = []     # Log de llamadas
```

### StopReason (Enum)

```python
class StopReason(Enum):
    COMPLETE = "complete"                  # LLM terminó normalmente
    MAX_TURNS = "max_turns"                # Límite de turnos
    REPEATED_CALL = "repeated_call"        # Loop detectado
    CONSECUTIVE_ERRORS = "consecutive_errors"  # Muchos errores
```

### ToolResult

```python
@dataclass
class ToolResult:
    success: bool
    output: str
    error: str | None = None
    metadata: dict[str, Any] | None = None
```

---

## Integración con Tools

### Tool Interface

```python
class Tool(ABC):
    @property
    def name(self) -> str: ...

    @property
    def description(self) -> str: ...

    @property
    def parameters(self) -> dict: ...  # JSON Schema

    async def execute(self, **kwargs) -> ToolResult: ...

    def get_schema(self) -> dict: ...  # Para LLM function calling

    def validate_args(self, args) -> tuple[bool, str | None]: ...
```

### ToolRegistry

```python
class ToolRegistry:
    def register(self, tool: Tool) -> None
    def get_tools_schema(self) -> list[dict]  # Para LLM
    async def dispatch(self, name: str, args: dict) -> ToolResult
```

### Flujo de Dispatch

```
AgentLoop                          ToolRegistry                    Tool
    │                                   │                            │
    │ dispatch("bash", {"cmd":"ls"})    │                            │
    │ ─────────────────────────────────►│                            │
    │                                   │                            │
    │                                   │ get("bash")                │
    │                                   │ ──────────────────────────►│
    │                                   │                            │
    │                                   │ validate_args(args)        │
    │                                   │ ──────────────────────────►│
    │                                   │                            │
    │                                   │◄─────── (True, None) ──────│
    │                                   │                            │
    │                                   │ execute(**args)            │
    │                                   │ ──────────────────────────►│
    │                                   │                            │
    │                                   │◄──── ToolResult ───────────│
    │                                   │                            │
    │◄──────── ToolResult ──────────────│                            │
    │                                   │                            │
```

---

## System Prompt

El prompt del sistema se construye dinámicamente:

```python
SYSTEM_PROMPT = """You are Rumi, a helpful assistant that can execute commands safely in a sandboxed environment.

You have access to the following tools:
{tools_description}

When you need to use a tool, respond with a tool call. Always explain what you're doing before executing commands.

Important:
- Commands run in an isolated Docker container
- No network access from the container
- Files persist in /workspace during the session
- Be careful with destructive operations

If you cannot complete a task with the available tools, explain why."""


def build_system_prompt(tools_schema: list[dict]) -> str:
    tools_desc = "\n".join(
        f"- {t['function']['name']}: {t['function']['description']}"
        for t in tools_schema
    )
    return SYSTEM_PROMPT.format(tools_description=tools_desc)
```

**Resultado:**
```
You are Rumi...

You have access to the following tools:
- bash: Execute a bash command in the sandbox
- web_fetch: Fetch content from a URL

...
```

---

## Patrones de Diseño

### 1. ReAct Pattern

El ciclo Think-Act-Observe es la implementación del patrón ReAct de Yao et al. (2022):

```
Thought: Necesito listar los archivos del directorio
Action: bash({"command": "ls -la"})
Observation: [output del comando]
Thought: Veo que hay un archivo readme.md, voy a leerlo
Action: bash({"command": "cat readme.md"})
Observation: [contenido del archivo]
Thought: Ya tengo la información, puedo responder
Answer: El proyecto es...
```

### 2. Strategy Pattern (Implícito)

Las herramientas son intercambiables a través del registry:

```python
registry.register(BashTool(sandbox))
registry.register(WebFetchTool())
# Agregar nuevas herramientas sin modificar AgentLoop
```

### 3. Command Pattern

Cada tool call es un objeto que encapsula la acción:

```python
{
    "name": "bash",
    "args": {"command": "ls -la"}
}
```

### 4. Template Method (Parcial)

El ciclo principal es fijo, pero las herramientas definen `execute()`:

```python
# AgentLoop define el ciclo (template)
for turn in range(max_turns):
    # think
    # act → tool.execute()  ← método que varía
    # observe
```

### 5. Dependency Injection

El cliente Groq y registry se inyectan:

```python
def __init__(
    self,
    registry: ToolRegistry,          # Inyectado
    config: AgentConfig | None = None,
    groq_client: AsyncGroq | None = None,  # Inyectado (facilita testing)
)
```

---

## Análisis de Fortalezas

### 1. Simplicidad
- ~180 líneas de código para el loop completo
- Sin dependencias más allá de groq SDK
- Fácil de entender y modificar

### 2. Robustez
- 3 circuit breakers independientes
- Cada uno cubre un tipo diferente de fallo
- Reset automático de contadores en éxito

### 3. Testabilidad
- Cliente Groq inyectable → mock fácil
- ToolRegistry desacoplado → tools mockeables
- 8+ tests cubriendo todos los escenarios

### 4. Extensibilidad
- Nuevas herramientas sin tocar AgentLoop
- Configuración via dataclass
- Historial opcional para compatibilidad

### 5. Observabilidad
- `tool_calls` log en resultado
- `turns` contador
- `stop_reason` explícito

---

## Análisis de Debilidades

### 1. Sin Streaming

**Problema:** El usuario espera hasta que termina todo el ciclo.

```python
# Todo es blocking
response = await self.client.chat.completions.create(...)
```

**Impacto:** Mala UX en tareas largas, no hay feedback incremental.

### 2. Sin Cancelación

**Problema:** No hay forma de interrumpir un ciclo en progreso.

```python
# No hay check de cancellation token
for turn in range(max_turns):
    # No hay: if cancelled: break
```

**Impacto:** El `/stop` de Telegram solo libera el lock, no detiene el LLM.

### 3. Sin Retry Inteligente

**Problema:** Los errores cuentan igual aunque sean transitorios.

```python
# Error de red temporal cuenta igual que error de validación
if not result.success:
    self._consecutive_errors += 1
```

**Impacto:** Puede detenerse por errores recuperables.

### 4. Sin Paralelismo de Tools

**Problema:** Las herramientas se ejecutan secuencialmente.

```python
for tool_call in assistant_message.tool_calls:
    result = await self.registry.dispatch(...)  # Una a la vez
```

**Impacto:** Si el LLM pide 3 tools, toma 3x el tiempo.

### 5. Prompt Hardcoded

**Problema:** El system prompt está en código.

```python
SYSTEM_PROMPT = """You are Rumi..."""  # No configurable
```

**Impacto:** Cambiar el comportamiento requiere modificar código.

### 6. Sin Memoria de Herramientas

**Problema:** No recuerda resultados de tools entre sesiones.

```
Sesión 1: bash("pip list") → lista de paquetes
Sesión 2: "¿qué paquetes hay?" → tiene que ejecutar de nuevo
```

**Impacto:** Trabajo redundante.

---

## Comparación con Otros Frameworks

| Aspecto | Rumi | LangChain | AutoGPT |
|---------|----------|-----------|---------|
| Líneas de código | ~180 | ~10k+ | ~5k+ |
| Circuit breakers | 3 | Configurable | Pocos |
| Streaming | No | Sí | Sí |
| Paralelismo | No | Sí | Sí |
| Memory | Externa | Integrada | Integrada |
| Plugins | Via registry | Agents/Tools | Plugins |
| Complejidad | Baja | Alta | Media |

---

## Código Anotado

### Ciclo Principal

```python
async def run(self, message: str, chat_id: str = None, history: list = None) -> AgentResult:
    self._reset_state()  # Limpia contadores de circuit breakers

    # 1. CONSTRUIR MENSAJES
    messages = [
        {"role": "system", "content": build_system_prompt(self.registry.get_tools_schema())},
    ]
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": message})

    tool_calls_log = []
    final_response = ""

    # 2. CICLO PRINCIPAL
    for turn in range(self.config.max_turns):
        # THINK: Llamar al LLM
        response = await self.client.chat.completions.create(
            model=self.config.model,
            messages=messages,
            tools=self.registry.get_tools_schema() or None,
            tool_choice="auto"
        )

        assistant_message = response.choices[0].message

        # ¿El LLM quiere usar herramientas?
        if assistant_message.tool_calls:
            messages.append(assistant_message.model_dump())

            # ACT: Ejecutar cada herramienta
            for tool_call in assistant_message.tool_calls:
                tool_name = tool_call.function.name
                tool_args = json.loads(tool_call.function.arguments)

                call_record = {"name": tool_name, "args": tool_args}
                tool_calls_log.append(call_record)

                # CIRCUIT BREAKER: ¿Llamada repetida?
                if self._check_repeated_call(call_record):
                    return AgentResult(
                        response="Stopped: repeated tool call",
                        stop_reason=StopReason.REPEATED_CALL,
                        turns=turn + 1,
                        tool_calls=tool_calls_log
                    )

                # Ejecutar herramienta
                result = await self.registry.dispatch(tool_name, tool_args)

                # CIRCUIT BREAKER: ¿Errores consecutivos?
                if not result.success:
                    self._consecutive_errors += 1
                    if self._consecutive_errors >= self.config.max_consecutive_errors:
                        return AgentResult(
                            response=f"Stopped: {n} consecutive errors",
                            stop_reason=StopReason.CONSECUTIVE_ERRORS,
                            turns=turn + 1,
                            tool_calls=tool_calls_log
                        )
                else:
                    self._consecutive_errors = 0

                # OBSERVE: Agregar resultado
                tool_response = format_tool_result(tool_name, result.success, result.output, result.error)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": tool_response
                })
        else:
            # LLM terminó, retornar respuesta
            return AgentResult(
                response=assistant_message.content or "",
                stop_reason=StopReason.COMPLETE,
                turns=turn + 1,
                tool_calls=tool_calls_log
            )

    # CIRCUIT BREAKER: Max turns alcanzado
    return AgentResult(
        response=final_response or "Max turns reached",
        stop_reason=StopReason.MAX_TURNS,
        turns=self.config.max_turns,
        tool_calls=tool_calls_log
    )
```

---

## Métricas

| Métrica | Valor |
|---------|-------|
| Líneas de código (loop.py) | ~183 |
| Líneas de código (prompt.py) | ~39 |
| Tests | 8 casos |
| Dependencias | groq (SDK) |
| Max turns default | 10 |
| Max errors default | 3 |
| Max repeated default | 2 |

---

## Conclusiones

El AgentLoop de Rumi es una implementación **minimalista pero completa** del patrón ReAct:

1. **Suficiente para su propósito**: Un asistente personal con 2 herramientas
2. **Bien protegido**: 3 circuit breakers cubren los casos de loop infinito
3. **Extensible**: Agregar herramientas no requiere modificar el loop
4. **Testeable**: Inyección de dependencias facilita mocking

Las limitaciones (sin streaming, sin cancelación, sin paralelismo) son **trade-offs conscientes** para mantener ~200 líneas de código claro y mantenible.

Para casos más complejos, se recomendaría migrar a LangChain o similar, pero para Rumi el enfoque actual es óptimo.
