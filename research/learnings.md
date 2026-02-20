# Rumi - Research & Learnings

Este documento resume los tópicos técnicos y lecciones aprendidas durante el desarrollo de Rumi.

---

## 1. Docker SDK (docker-py)

### Conceptos clave
- **Containers vs Images**: Las imágenes son plantillas inmutables; los contenedores son instancias ejecutables
- **Detached mode**: `containers.run(detach=True)` retorna inmediatamente, permitiendo control asíncrono

### Patrones aprendidos

```python
# Crear contenedor de larga duración
container = client.containers.run(
    image="rumi-runner:latest",
    detach=True,
    command=["sleep", "infinity"]
)

# IMPORTANTE: reload() antes de verificar estado
container.reload()
assert container.status == "running"
```

### Flags de seguridad para sandboxing

| Flag | Propósito |
|------|-----------|
| `read_only=True` | Sistema de archivos solo lectura |
| `cap_drop=["ALL"]` | Elimina todas las capabilities de Linux |
| `network_mode="none"` | Sin acceso a red |
| `security_opt=["no-new-privileges"]` | Previene escalación de privilegios |
| `pids_limit=128` | Límite de procesos (fork bomb protection) |
| `mem_limit="512m"` | Límite de memoria |
| `cpu_period/quota` | Límite de CPU |

### Volúmenes y tmpfs

```python
# Workspace writable en contenedor read-only
volumes={workspace_path: {"bind": "/workspace", "mode": "rw"}}

# tmpfs para /tmp cuando root es read-only
tmpfs={"/tmp": "size=64m,mode=1777"}
```

---

## 2. Groq API (LLM Integration)

### Cliente asíncrono

```python
from groq import AsyncGroq

client = AsyncGroq(api_key=os.environ["GROQ_API_KEY"])
response = await client.chat.completions.create(
    model="llama-3.3-70b-versatile",
    messages=messages,
    tools=tools
)
```

### Tool Calling

```python
# Extraer tool calls del mensaje del asistente
message = response.choices[0].message
if message.tool_calls:
    for tool_call in message.tool_calls:
        name = tool_call.function.name
        # Los argumentos vienen como string JSON
        args = json.loads(tool_call.function.arguments)
```

### Formato de herramientas

```python
tools = [{
    "type": "function",
    "function": {
        "name": "bash",
        "description": "Execute a bash command",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {"type": "string"}
            },
            "required": ["command"]
        }
    }
}]
```

---

## 3. Agent Loop Pattern

### Ciclo Think-Act-Observe

```
┌─────────────────────────────────────┐
│              THINK                  │
│   LLM decide qué herramienta usar   │
└──────────────┬──────────────────────┘
               ▼
┌─────────────────────────────────────┐
│               ACT                   │
│   Ejecutar herramienta seleccionada │
└──────────────┬──────────────────────┘
               ▼
┌─────────────────────────────────────┐
│             OBSERVE                 │
│   Agregar resultado al historial    │
└──────────────┬──────────────────────┘
               │
               ▼
        ¿Terminó? ──No──→ THINK
               │
              Yes
               ▼
           Respuesta
```

### Circuit Breakers implementados

1. **Repetición de tool_call**: Si el mismo llamado se repite 2 veces consecutivas → parar
2. **Errores consecutivos**: 3 errores seguidos → parar
3. **Max turns**: Límite duro de iteraciones

---

## 4. SSRF Protection (web_fetch)

### El problema
Server-Side Request Forgery permite a un atacante hacer que el servidor acceda a recursos internos.

### Solución implementada

```python
# 1. Resolver DNS primero
addr_info = socket.getaddrinfo(hostname, port)
ip = addr_info[0][4][0]

# 2. Validar IP antes de conectar
BLOCKED_RANGES = [
    ipaddress.ip_network("127.0.0.0/8"),      # Loopback
    ipaddress.ip_network("10.0.0.0/8"),       # Private
    ipaddress.ip_network("172.16.0.0/12"),    # Private
    ipaddress.ip_network("192.168.0.0/16"),   # Private
    ipaddress.ip_network("169.254.0.0/16"),   # Link-local
]

ip_obj = ipaddress.ip_address(ip)
for network in BLOCKED_RANGES:
    if ip_obj in network:
        raise SSRFError(f"Blocked IP: {ip}")
```

### Por qué resolver DNS primero
- Evita DNS rebinding attacks
- El atacante no puede hacer que `evil.com` resuelva a `127.0.0.1`

---

## 5. pytest-asyncio

### Configuración básica

```python
import pytest

@pytest.mark.asyncio
async def test_async_function():
    result = await some_async_operation()
    assert result == expected
```

### Fixtures asíncronas

```python
@pytest.fixture
async def sandbox():
    manager = SandboxManager()
    await manager.create("test-session")
    yield manager
    await manager.destroy("test-session")
```

### Mocking con monkeypatch

```python
def test_with_env(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    # El test usa la variable mockeada
```

---

## 6. Alpine Linux en Docker

### Particularidades

| Característica | Implicación |
|---------------|-------------|
| Usa musl libc | Algunas librerías de glibc no funcionan |
| BusyBox por defecto | Incluye wget, nc, y muchos utils |
| apk package manager | Diferente a apt/yum |

### Optimización de imágenes

```dockerfile
# Evitar cache de paquetes
RUN apk add --no-cache python3

# Remover herramientas de red si no se necesitan
RUN apk del wget && rm -f /usr/bin/nc
```

### Gotcha: DNS en Alpine
- `example.com` puede no resolver en algunos entornos Alpine
- Usar `httpbin.org` u otros hosts confiables para tests

---

## 7. Session Management

### Lock por sesión

```python
class SessionManager:
    def __init__(self):
        self._locks: dict[str, asyncio.Lock] = {}

    def get_lock(self, chat_id: str) -> asyncio.Lock:
        if chat_id not in self._locks:
            self._locks[chat_id] = asyncio.Lock()
        return self._locks[chat_id]
```

### Patrón de uso

```python
lock = session_manager.get_lock(chat_id)
if lock.locked():
    return "⏳ Ya estoy trabajando en tu solicitud anterior"

async with lock:
    result = await agent.run(message)
```

---

## 8. python-telegram-bot v21+

### Patrón Application (async)

```python
from telegram.ext import Application, CommandHandler, MessageHandler

app = Application.builder().token(TOKEN).build()
app.add_handler(CommandHandler("start", start_handler))
app.add_handler(MessageHandler(filters.TEXT, message_handler))

# Ejecutar
await app.run_polling()
```

### Handlers asíncronos

```python
async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    text = update.message.text

    # Responder
    await update.message.reply_text("Procesando...")
```

---

## 9. Seguridad en Ejecución de Comandos

### Por qué NO usar `bash -c`

```python
# PELIGROSO - permite inyección de shell
subprocess.run(["bash", "-c", user_input])

# SEGURO - sin interpretación de shell
subprocess.run(shlex.split(user_input), shell=False)
```

### Allowlist de comandos

```python
ALLOWED_COMMANDS = {"ls", "cat", "echo", "python", "pip", ...}

def validate_command(argv: list[str]) -> bool:
    if not argv:
        return False
    base_command = os.path.basename(argv[0])
    return base_command in ALLOWED_COMMANDS
```

### Limitaciones aceptadas
- No pipes (`|`)
- No redirecciones (`>`, `<`)
- No encadenamiento (`&&`, `;`)

Estas limitaciones son intencionales para seguridad.

---

## 10. Observabilidad con JSONL

### Formato de logs

```python
import json
from datetime import datetime

def log_event(event: dict):
    event["timestamp"] = datetime.utcnow().isoformat()
    print(json.dumps(event))
```

### Campos estándar para ejecución

```json
{
  "timestamp": "2024-01-15T10:30:00Z",
  "container_id": "abc123",
  "argv": ["python", "script.py"],
  "duration_ms": 1500,
  "exit_code": 0,
  "truncated": false,
  "stopped_reason": null
}
```

### Ventajas de JSONL
- Una línea = un evento (fácil de parsear)
- Compatible con `jq` para análisis
- Fácil de ingestar en sistemas de logs

---

## Resumen de Lecciones

1. **Docker como sandbox**: Combinación de flags de seguridad provee aislamiento robusto
2. **SSRF es sutil**: Resolver DNS antes de validar IP es crucial
3. **Agent loops necesitan circuit breakers**: Sin ellos, pueden correr infinitamente
4. **`shell=False` siempre**: Nunca interpretar comandos de usuario con shell
5. **Locks por sesión**: Esencial para evitar race conditions en chatbots
6. **Alpine tiene quirks**: Conocer las diferencias con distros tradicionales
7. **Testing async**: pytest-asyncio simplifica mucho el testing de código async
8. **Observabilidad desde el inicio**: JSONL logs facilitan debugging en producción
