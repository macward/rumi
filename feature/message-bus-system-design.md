# MessageBus System Design — Rumi

## Problem Statement

Rumi hoy tiene dos interfaces funcionando — CLI (`cli.py`) y Telegram
(`bot.py`) — pero ambas están directamente acopladas al AgentLoop. Cada una
registra tools manualmente y llama al agente de forma síncrona. Este modelo
tiene limitaciones fundamentales:

- **Canales aislados**: CLI y Telegram son dos entry points separados que
  no comparten infraestructura de mensajería
- **Sin background work**: un sub-agente no puede notificar cuando termina
- **Sin proactividad**: no puede despertar solo (cron, heartbeat, monitoring)
- **Acoplamiento fuerte**: cada interfaz está directamente atada al AgentLoop
- **No escala a más canales**: agregar Discord/WhatsApp requiere duplicar
  el patrón de `bot.py` cada vez

El MessageBus resuelve esto al desacoplar **quién envía** de **quién procesa**
de **quién entrega**. Es la pieza fundacional que habilita todo lo demás.

## Qué habilita el MessageBus

```
Sin MessageBus (hoy):

  cli.py ──────────► AgentLoop ──────────► CLI stdout
       síncrono              síncrono

  bot.py ──────────► AgentLoop ──────────► Telegram API
       síncrono              síncrono

  (dos procesos separados, sin comunicación entre sí)

Con MessageBus (futuro):

  CLI Adapter ─────┐                    ┌──► CLI stdout
  Telegram Bot ────┤                    ├──► Telegram API
  Cron ────────────┤──► MessageBus ─────┤──► Discord API
  Heartbeat ───────┤    (InQ / OutQ)    ├──► (más canales)
  SubAgents ───────┘         │          └──► Webhooks
                             ▼
                        AgentLoop
                      (consume InQ,
                       produce OutQ)

  (un solo proceso, todos los canales unificados)
```

Cada productor (CLI, Telegram, cron, sub-agente) publica un `InboundMessage`
al bus. El AgentLoop consume, procesa, y publica un `OutboundMessage`.
El dispatcher rutea la respuesta al canal correcto.

## Investigación: nanobot

nanobot implementa exactamente este patrón en ~115 líneas totales:

| Archivo | Líneas | Función |
|---------|--------|---------|
| `bus/events.py` | ~35 | InboundMessage, OutboundMessage dataclasses |
| `bus/queue.py` | ~80 | MessageBus con dos asyncio.Queue |
| | | + subscribe/dispatch pattern para outbound |

### Hallazgos clave de nanobot

1. **El bus existe siempre, incluso en CLI** — pero CLI lo bypasea usando
   `process_direct()` que construye un InboundMessage interno y llama
   `_process_message()` directamente, sin pasar por la queue.

2. **Gateway mode usa el bus activamente**: `agent.run()` es un loop infinito
   que hace `await bus.consume_inbound()` → `_process_message()` →
   `bus.publish_outbound()`.

3. **Channels publican al inbound, consumen del outbound**: Cada canal
   (Telegram, Discord) recibe mensajes de su API, los envuelve en
   `InboundMessage`, y publica al bus. El `ChannelManager` tiene un dispatcher
   que consume outbound y rutea al canal correcto.

4. **SubagentManager publica resultados como system messages**: Cuando un
   sub-agente termina, publica `InboundMessage(channel="system")` al bus.
   El AgentLoop detecta `channel == "system"` y lo procesa como un mensaje
   interno, generando la respuesta que llega al usuario.

5. **Cron/Heartbeat también publican al bus**: Son productores más que
   publican InboundMessages periódicamente.

### Patrón de orquestación (gateway command de nanobot)

```python
bus = MessageBus()
agent = AgentLoop(bus=bus, ...)
channels = ChannelManager(config, bus)

async def run():
    await asyncio.gather(
        agent.run(),           # consume inbound, produce outbound
        channels.start_all(),  # channels produce inbound, consume outbound
    )
```

## Arquitectura para Rumi

Adaptamos el patrón de nanobot pero con mejoras:
- Tipado más fuerte (enums para canales)
- Middleware hooks (logging, filtering)
- Modo dual explícito (direct vs bus)
- Preparado para sub-agentes fire-and-forget

### Diagrama de Componentes

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           Productores                                    │
│                                                                          │
│  ┌─────────┐  ┌───────────┐  ┌──────────┐  ┌────────────┐  ┌────────┐  │
│  │   CLI   │  │ Telegram  │  │   Cron   │  │ SubAgents  │  │ Heart- │  │
│  │ Adapter │  │   Bot     │  │ Service  │  │  Manager   │  │  beat  │  │
│  │(existe) │  │ (existe)  │  │ (futuro) │  │ (diseñado) │  │(futuro)│  │
│  └────┬────┘  └─────┬─────┘  └────┬─────┘  └─────┬──────┘  └───┬────┘  │
│       │             │             │               │             │        │
│       └─────────────┴─────────────┴───────┬───────┴─────────────┘        │
│                                           │                              │
│                                    publish_inbound()                     │
│                                           │                              │
│  ┌────────────────────────────────────────▼──────────────────────────┐   │
│  │                        MessageBus                                  │   │
│  │                                                                    │   │
│  │   ┌──────────────────────┐    ┌──────────────────────┐            │   │
│  │   │   Inbound Queue      │    │   Outbound Queue     │            │   │
│  │   │  asyncio.Queue       │    │   asyncio.Queue      │            │   │
│  │   │                      │    │                       │            │   │
│  │   │  ← InboundMessage    │    │  ← OutboundMessage   │            │   │
│  │   └──────────┬───────────┘    └───────────┬───────────┘            │   │
│  │              │                            │                        │   │
│  │         consume_inbound()           consume_outbound()             │   │
│  │              │                            │                        │   │
│  │   ┌──────────┴──────────┐                 │                        │   │
│  │   │  Middleware Chain   │                 │                        │   │
│  │   │  (log, filter, etc) │                 │                        │   │
│  │   └──────────┬──────────┘                 │                        │   │
│  └──────────────┼────────────────────────────┼────────────────────────┘   │
│                 │                            │                            │
│                 ▼                            │                            │
│  ┌──────────────────────────────┐            │                            │
│  │         AgentLoop            │            │                            │
│  │                              │            │                            │
│  │  Modo Gateway:               │            │                            │
│  │    while running:            │            │                            │
│  │      msg = consume_inbound() │            │                            │
│  │      resp = process(msg)     │            │                            │
│  │      publish_outbound(resp) ─┼────────────┘                            │
│  │                              │                                         │
│  │  Modo Direct:                │                                         │
│  │    resp = process_direct(msg)│  ← bypasea bus, retorna directo         │
│  └──────────────────────────────┘                                         │
│                                                                           │
│  ┌────────────────────────────────────────────────────────────────────┐   │
│  │                        Dispatcher                                  │   │
│  │                                                                    │   │
│  │   consume_outbound() → rutea OutboundMessage al canal correcto     │   │
│  │                                                                    │   │
│  │   msg.channel == "cli"      → CLIAdapter.send()                    │   │
│  │   msg.channel == "telegram" → TelegramChannel.send()               │   │
│  │   msg.channel == "discord"  → DiscordChannel.send()                │   │
│  └────────────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────────────┘
```

### Data Flow: Mensaje de Telegram con Sub-Agente

```
1. Usuario manda "Investigá X" por Telegram
    │
    ▼
2. TelegramChannel._handle_message()
    → Construye InboundMessage(channel="telegram", chat_id="12345", ...)
    → bus.publish_inbound(msg)
    │
    ▼
3. AgentLoop.run() consume del bus
    → msg = bus.consume_inbound()
    → response = _process_message(msg)
    │
    ├── AgentLoop decide usar spawn_background
    │   → SubAgentManager.spawn_background(task, origin="telegram:12345")
    │   → Retorna "Investigando en background..."
    │
    ▼
4. AgentLoop publica respuesta inmediata
    → bus.publish_outbound(OutboundMessage(channel="telegram", ...))
    │
    ▼
5. Dispatcher rutea a TelegramChannel.send()
    → Usuario ve "Investigando en background..."
    
    ... mientras tanto, en background ...

6. Sub-agente termina su investigación
    → bus.publish_inbound(InboundMessage(
        channel="system",
        sender_id="subagent",
        chat_id="telegram:12345",    ← codifica destino original
        content="[Resultado de la investigación...]"
      ))
    │
    ▼
7. AgentLoop consume el system message
    → Detecta channel == "system"
    → Parsea destino original del chat_id
    → Procesa resultado, genera resumen
    → bus.publish_outbound(OutboundMessage(channel="telegram", ...))
    │
    ▼
8. Dispatcher rutea a Telegram
    → Usuario recibe "Acá están los resultados de la investigación..."
```

## Interfaces Core

### Eventos

```python
# src/rumi/bus/events.py

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class InboundMessage:
    """Mensaje entrante hacia el agente.

    Inmutable por diseño — una vez creado, no se modifica.
    Productores: CLI, canales (Telegram, etc), cron, heartbeat, sub-agentes.
    Consumidor: AgentLoop.
    """
    channel: str          # "cli" | "telegram" | "system" | "cron" | "heartbeat"
    sender_id: str        # user ID, "subagent", "cron", "heartbeat"
    chat_id: str          # identificador de conversación
    content: str          # el mensaje
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def session_key(self) -> str:
        """Clave única de sesión. Combina canal + chat para aislar conversaciones."""
        return f"{self.channel}:{self.chat_id}"

    @property
    def is_system(self) -> bool:
        """Mensaje interno del sistema (sub-agente, cron, etc)."""
        return self.channel == "system"


@dataclass(frozen=True)
class OutboundMessage:
    """Mensaje saliente del agente hacia el usuario.

    Inmutable por diseño.
    Productor: AgentLoop.
    Consumidores: Dispatcher → canales.
    """
    channel: str          # destino: "cli" | "telegram" | "discord"
    chat_id: str          # a quién
    content: str          # respuesta
    reply_to: str | None = None  # ID del mensaje al que responde (opcional)
    metadata: dict[str, Any] = field(default_factory=dict)
```

### MessageBus

```python
# src/rumi/bus/queue.py

import asyncio
from typing import Callable, Awaitable

from rumi.bus.events import InboundMessage, OutboundMessage


class MessageBus:
    """Bus de mensajes async que desacopla productores del consumidor.

    Dos colas independientes:
    - inbound: mensajes hacia el agente (productores → AgentLoop)
    - outbound: respuestas del agente (AgentLoop → canales)

    Thread-safe por diseño (asyncio.Queue es safe dentro del mismo event loop).
    """

    def __init__(self, max_inbound: int = 100, max_outbound: int = 100):
        self._inbound: asyncio.Queue[InboundMessage] = asyncio.Queue(maxsize=max_inbound)
        self._outbound: asyncio.Queue[OutboundMessage] = asyncio.Queue(maxsize=max_outbound)
        self._running = False

    # --- Inbound (productores → agente) ---

    async def publish_inbound(self, msg: InboundMessage) -> None:
        """Publica un mensaje para que el agente lo procese."""
        await self._inbound.put(msg)

    async def consume_inbound(self) -> InboundMessage:
        """Consume el próximo mensaje inbound. Bloquea hasta que haya uno."""
        return await self._inbound.get()

    # --- Outbound (agente → canales) ---

    async def publish_outbound(self, msg: OutboundMessage) -> None:
        """Publica una respuesta del agente para que los canales la entreguen."""
        await self._outbound.put(msg)

    async def consume_outbound(self) -> OutboundMessage:
        """Consume el próximo mensaje outbound. Bloquea hasta que haya uno."""
        return await self._outbound.get()

    # --- Lifecycle ---

    @property
    def inbound_pending(self) -> int:
        return self._inbound.qsize()

    @property
    def outbound_pending(self) -> int:
        return self._outbound.qsize()
```

### Dispatcher

El dispatcher consume del outbound queue y rutea al canal correcto.
Vive en el ChannelManager (futuro), pero podemos definir la interfaz:

```python
# src/rumi/bus/dispatcher.py

import asyncio
from typing import Callable, Awaitable

from rumi.bus.events import OutboundMessage
from rumi.bus.queue import MessageBus


# Type alias para un handler de canal
ChannelSender = Callable[[OutboundMessage], Awaitable[None]]


class Dispatcher:
    """Rutea mensajes outbound al canal correcto.

    Los canales se registran como handlers. El dispatcher corre como
    background task consumiendo del outbound queue.
    """

    def __init__(self, bus: MessageBus):
        self._bus = bus
        self._handlers: dict[str, ChannelSender] = {}
        self._running = False

    def register(self, channel: str, handler: ChannelSender) -> None:
        """Registra un handler para un canal."""
        self._handlers[channel] = handler

    def unregister(self, channel: str) -> None:
        """Desregistra un handler."""
        self._handlers.pop(channel, None)

    async def run(self) -> None:
        """Loop principal: consume outbound y rutea al handler correcto."""
        self._running = True
        while self._running:
            try:
                msg = await asyncio.wait_for(
                    self._bus.consume_outbound(),
                    timeout=1.0,
                )
                handler = self._handlers.get(msg.channel)
                if handler:
                    try:
                        await handler(msg)
                    except Exception as e:
                        # Log error pero no crashea el dispatcher
                        logger.error(f"Dispatcher error [{msg.channel}]: {e}")
                else:
                    logger.warning(f"No handler for channel: {msg.channel}")
            except asyncio.TimeoutError:
                continue

    def stop(self) -> None:
        self._running = False
```

## Integración con AgentLoop: Modo Dual

El AgentLoop soporta dos modos de operación:

### Modo Direct (CLI + Telegram hoy, sin bus activo)

```python
# cli.py llama process_direct() — bypasea el bus
response = await agent.process_direct("Hola", session_key="cli:direct")
print(response)

# bot.py hace lo mismo desde Telegram
response = await agent.process_direct(message.text, session_key=f"telegram:{chat_id}")
await message.reply(response)
```

Esto es lo que Rumi hace **hoy** en ambas interfaces. No requiere MessageBus.
Internamente, `process_direct()` construye un InboundMessage y llama
`_process_message()` directamente.

### Modo Gateway (daemon, con bus activo)

```python
# El gateway unifica CLI y Telegram en un solo proceso
bus = MessageBus()
agent = AgentLoop(bus=bus, ...)
dispatcher = Dispatcher(bus)

# Registrar los dos canales existentes
dispatcher.register("cli", cli_sender)
dispatcher.register("telegram", telegram_sender)

# Todo corre en paralelo — un solo proceso
await asyncio.gather(
    agent.run_gateway(),    # consume inbound, produce outbound
    dispatcher.run(),       # consume outbound, rutea a canales
    telegram.start(),       # produce inbound desde Telegram
    cli.start(),            # produce inbound desde CLI (stdin)
)
```

**Beneficio clave**: hoy CLI y Telegram son dos procesos separados
con dos instancias de AgentLoop. Con el gateway, comparten el mismo
agente, la misma sesión, y las mismas capacidades.

### Cambios al AgentLoop

El AgentLoop necesita **dos métodos** de entry point:

```python
class AgentLoop:
    def __init__(self, registry, config, groq_client, bus: MessageBus | None = None):
        self.bus = bus
        # ... resto igual

    # Modo Direct — lo que existe hoy en cli.py y bot.py, sin cambios
    async def process_direct(self, message: str, chat_id: str = "default") -> str:
        """Procesa un mensaje directamente. Retorna la respuesta.
        
        Usado por:
        - cli.py: process_direct(msg, chat_id="cli:direct")
        - bot.py: process_direct(msg, chat_id=f"telegram:{tg_chat_id}")
        """
        # No usa el bus, llama _process_message() directo
        ...

    # Modo Gateway — NUEVO, consume del bus
    async def run_gateway(self) -> None:
        """Loop que consume mensajes del bus. Para modo daemon."""
        assert self.bus is not None, "MessageBus required for gateway mode"
        self._running = True

        while self._running:
            try:
                msg = await asyncio.wait_for(
                    self.bus.consume_inbound(),
                    timeout=1.0,
                )

                # System messages (sub-agentes, cron)
                if msg.is_system:
                    response = await self._process_system_message(msg)
                else:
                    response = await self._process_message(msg)

                if response and self.bus:
                    await self.bus.publish_outbound(response)

            except asyncio.TimeoutError:
                continue

    async def _process_system_message(self, msg: InboundMessage) -> OutboundMessage | None:
        """Procesa mensajes internos (sub-agentes, cron).

        El chat_id contiene "canal_original:chat_id_original" para
        rutear la respuesta al destino correcto.
        """
        # Parsear destino original
        if ":" in msg.chat_id:
            origin_channel, origin_chat_id = msg.chat_id.split(":", 1)
        else:
            origin_channel, origin_chat_id = "cli", msg.chat_id

        # Procesar como mensaje normal pero en la sesión del origen
        result = await self._process_message(InboundMessage(
            channel=origin_channel,
            sender_id=msg.sender_id,
            chat_id=origin_chat_id,
            content=msg.content,
        ))

        return result

    def stop(self) -> None:
        self._running = False
```

## Integración con Sub-Agentes

Con el MessageBus, el SubAgentManager gana el modo fire-and-forget:

```python
class SubAgentManager:
    def __init__(self, ..., bus: MessageBus | None = None):
        self.bus = bus
        self._running_tasks: dict[str, asyncio.Task] = {}

    # MODO 1: Síncrono (TaskPlan) — ya diseñado, sin cambios
    async def execute_plan(self, plan: TaskPlan, ...) -> dict[str, TaskResult]:
        """Ejecuta plan completo. Bloqueante. No necesita bus."""
        ...

    # MODO 2: Fire-and-forget — requiere MessageBus
    async def spawn_background(
        self,
        task: str,
        label: str | None = None,
        origin_channel: str = "cli",
        origin_chat_id: str = "direct",
    ) -> str:
        """Lanza sub-agente en background. Retorna inmediatamente.

        Cuando el sub-agente termina, publica resultado al MessageBus
        como InboundMessage(channel="system").
        """
        if self.bus is None:
            return "Error: background tasks require gateway mode"

        task_id = str(uuid.uuid4())[:8]
        display = label or task[:30] + ("..." if len(task) > 30 else "")

        bg_task = asyncio.create_task(
            self._run_and_announce(task_id, task, display, origin_channel, origin_chat_id)
        )
        self._running_tasks[task_id] = bg_task
        bg_task.add_done_callback(lambda _: self._running_tasks.pop(task_id, None))

        return f"Tarea '{display}' iniciada en background (id: {task_id})"

    async def _run_and_announce(
        self, task_id, task, label, origin_channel, origin_chat_id
    ):
        """Ejecuta sub-agente y publica resultado al bus."""
        try:
            result = await self._run_sub_agent(
                Task(id=task_id, role="general", instruction=task),
                dependency_context={},
                chat_id=f"{origin_channel}:{origin_chat_id}",
            )

            announcement = (
                f"[Background task '{label}' completed]\n\n"
                f"Task: {task}\n\n"
                f"Result:\n{result.output}\n\n"
                f"Summarize this naturally for the user."
            )
        except Exception as e:
            announcement = (
                f"[Background task '{label}' failed]\n\n"
                f"Task: {task}\n"
                f"Error: {e}\n\n"
                f"Let the user know briefly."
            )

        await self.bus.publish_inbound(InboundMessage(
            channel="system",
            sender_id="subagent",
            chat_id=f"{origin_channel}:{origin_chat_id}",
            content=announcement,
        ))

    @property
    def running_count(self) -> int:
        return len(self._running_tasks)
```

Y el tool correspondiente:

```python
class SpawnBackgroundTool(Tool):
    """Tool para tareas fire-and-forget. Solo disponible en gateway mode."""
    name = "spawn_background"
    description = (
        "Start a long-running task in the background. Returns immediately. "
        "Use for: research, monitoring, file processing, anything that takes time. "
        "The result will be announced when complete."
    )

    # Solo se registra si hay MessageBus
    # En modo CLI, este tool no existe → el LLM no lo ve
```

## Estructura del Módulo

```
src/rumi/
├── bus/                      # NUEVO — MessageBus
│   ├── __init__.py           # Exporta MessageBus, InboundMessage, OutboundMessage
│   ├── events.py             # InboundMessage, OutboundMessage dataclasses
│   ├── queue.py              # MessageBus (dos asyncio.Queue)
│   └── dispatcher.py         # Dispatcher (rutea outbound a canales)
│
├── agents/                   # Existente — se modifica
│   ├── loop.py               # + run_gateway(), _process_system_message()
│   └── sub/
│       ├── manager.py        # + spawn_background(), bus integration
│       └── spawn_bg_tool.py  # SpawnBackgroundTool (NUEVO)
│
├── interfaces/               # REFACTOR de cli.py + bot.py existentes
│   ├── __init__.py
│   ├── cli.py                # CLI adapter (existente → adaptar al bus)
│   └── telegram.py           # Telegram bot (existente → adaptar al bus)
│
├── channels/                 # FUTURO — canales adicionales
│   ├── __init__.py
│   ├── base.py               # BaseChannel ABC (extraer patrón de telegram.py)
│   ├── manager.py            # ChannelManager (init + lifecycle)
│   └── discord.py            # DiscordChannel (futuro)
│
├── gateway/                  # FUTURO — orquestación daemon
│   ├── __init__.py
│   └── server.py             # Gateway (wires bus + agent + channels)
│
├── tools/                    # Existente — sin cambios
├── sandbox/                  # Existente — sin cambios
└── session/                  # Existente — sin cambios
```

## Impacto en Código Existente

| Archivo | Cambio | Impacto |
|---------|--------|---------|
| `bus/events.py` | **Nuevo** | ~30 líneas |
| `bus/queue.py` | **Nuevo** | ~50 líneas |
| `bus/dispatcher.py` | **Nuevo** | ~50 líneas |
| `agents/loop.py` | **Modificar** | +40 líneas (run_gateway, _process_system_message) |
| `interfaces/cli.py` | **Refactor** | Adaptar como productor/consumidor del bus |
| `interfaces/telegram.py` | **Refactor** | Adaptar como productor/consumidor del bus |
| `agents/sub/manager.py` | **Modificar** | +50 líneas (spawn_background, _run_and_announce) |
| `agents/sub/spawn_bg_tool.py` | **Nuevo** | ~40 líneas |
| **Total nuevo** | | **~260 líneas** |

Los entry points existentes (`rumi chat` y el bot de Telegram) siguen
funcionando en modo direct. El bus se activa con `rumi gateway` que
unifica ambos canales en un solo proceso.

## Fases de Implementación

### Fase 1: Bus core + canales existentes (CLI + Telegram)
- [ ] `bus/events.py` — InboundMessage, OutboundMessage
- [ ] `bus/queue.py` — MessageBus
- [ ] `bus/dispatcher.py` — Dispatcher básico
- [ ] Adaptar `cli.py` como productor/consumidor del bus
- [ ] Adaptar `bot.py` (Telegram) como productor/consumidor del bus
- [ ] Tests: publish/consume, dispatch routing, ambos canales

### Fase 2: Gateway mode (proceso unificado)
- [ ] `agents/loop.py` — `run_gateway()` + `_process_system_message()`
- [ ] `rumi gateway` command que wirea bus + agent + dispatcher + canales
- [ ] CLI y Telegram corriendo en el mismo proceso vía bus
- [ ] Tests: gateway lifecycle, message routing multi-canal

### Fase 3: Sub-agentes fire-and-forget
- [ ] `agents/sub/manager.py` — `spawn_background()`, `_run_and_announce()`
- [ ] `agents/sub/spawn_bg_tool.py` — SpawnBackgroundTool
- [ ] Registro condicional: solo si bus está activo
- [ ] Tests: spawn, announce, routing de system messages

### Fase 4: Más canales + servicios periódicos
- [ ] `channels/base.py` — BaseChannel ABC (generalizar patrón de bot.py)
- [ ] `channels/manager.py` — ChannelManager
- [ ] Discord, WhatsApp como nuevos canales sobre la misma infra
- [ ] Cron service que publica al bus
- [ ] Heartbeat service

---

## Decisiones de Arquitectura

### ADR-025: MessageBus como infraestructura fundacional

**Status**: Aceptado

**Decisión**: Implementar un MessageBus basado en dos `asyncio.Queue` como
la capa de comunicación entre todos los componentes de Rumi.

**Contexto**: Rumi necesita evolucionar de CLI síncrono a un sistema que
soporte múltiples canales, sub-agentes background, y tareas periódicas.

**Rationale**:
- Desacopla productores de consumidores — agregar un canal no cambia el agente
- asyncio.Queue es la primitiva correcta: async, backpressure, zero-dependency
- nanobot valida el patrón en producción con 9 canales en ~80 líneas
- El bus es invisible para el modo CLI (process_direct bypasea el bus)

**Alternativas consideradas**:
- Redis pub/sub: overkill, agrega dependencia de infraestructura
- Callbacks directos: acopla canales al AgentLoop
- Actor model (e.g. aiodispatcher): demasiado abstracto para el caso de uso

**Consecuencias**:
- Todos los nuevos componentes (canales, cron, heartbeat) se diseñan como
  productores/consumidores del bus
- El AgentLoop necesita dos entry points (direct y gateway)
- La complejidad del sistema se centraliza en el bus y el dispatcher

### ADR-026: Modo dual — Direct y Gateway

**Status**: Aceptado

**Decisión**: El AgentLoop soporta dos modos de operación:
- `process_direct()`: síncrono, sin bus, para CLI y Telegram standalone
- `run_gateway()`: loop infinito, consume del bus, para daemon mode

**Rationale**:
- Los modos existentes (CLI vía `cli.py`, Telegram vía `bot.py`) no deben
  romperse ni degradarse — ambos usan `process_direct()` hoy
- Gateway mode es opt-in: solo se activa con `rumi gateway`
- En gateway mode, CLI y Telegram comparten el mismo AgentLoop
- nanobot usa exactamente este patrón (process_direct vs run)
- Un solo AgentLoop, dos entry points — DRY

**Consecuencias**:
- `bus` es parámetro opcional del AgentLoop
- Features que requieren bus (spawn_background) fallan gracefully en modo direct
- Tests del modo direct no necesitan MessageBus
- `rumi chat` y `bot.py` standalone siguen funcionando sin cambios

### ADR-027: System messages para comunicación interna

**Status**: Aceptado

**Decisión**: Los componentes internos (sub-agentes, cron) comunican resultados
al AgentLoop publicando `InboundMessage(channel="system")` al bus.

**Rationale**:
- Reutiliza la misma infraestructura (bus) para comunicación interna y externa
- El AgentLoop distingue mensajes del sistema con `msg.is_system`
- El destino original se codifica en `chat_id` (ej: `"telegram:12345"`)
- nanobot valida este patrón en producción

**Alternativas consideradas**:
- Cola separada para system messages: complejidad innecesaria
- Callbacks directos del sub-agente al canal: acopla sub-agentes a canales
- Evento/señal async: menos flexible, no pasa por el AgentLoop para síntesis

**Consecuencias**:
- `_process_system_message()` parsea el destino del chat_id
- El AgentLoop procesa el resultado y puede sintetizarlo antes de enviarlo
- Un sub-agente nunca habla directamente al usuario — siempre pasa por el orchestrator

### ADR-028: Dispatcher separado del bus

**Status**: Aceptado

**Decisión**: El dispatcher (ruteo outbound → canales) es un componente
separado del MessageBus, no parte de él.

**Rationale**:
- Single responsibility: el bus mueve mensajes, el dispatcher los rutea
- Permite testear el bus sin canales y vice versa
- Los handlers de canal se registran dinámicamente en el dispatcher
- nanobot mezcla dispatching en el ChannelManager — preferimos separar

**Consecuencias**:
- El Dispatcher necesita ser iniciado como background task junto al AgentLoop
- Los canales se registran en el Dispatcher, no en el bus
- En modo direct (sin gateway), no hay Dispatcher

### ADR-029: SpawnBackgroundTool solo disponible en gateway mode

**Status**: Aceptado

**Decisión**: El tool `spawn_background` solo se registra en el ToolRegistry
cuando el MessageBus está activo. En modo CLI, no existe.

**Rationale**:
- Fire-and-forget sin un listener es inútil (quién recibe el resultado?)
- El LLM no puede llamar un tool que no ve → no hay confusión
- En modo CLI, el LLM usa `spawn_agents` (síncrono) para delegar
- Cuando se activa gateway, el tool aparece automáticamente

**Consecuencias**:
- El registro de tools tiene un branch condicional basado en bus presence
- El system prompt lista `spawn_background` solo en gateway mode
- El LLM adapta su comportamiento según los tools disponibles

---

## Resumen: Por qué el bus vale la pena

El MessageBus son ~130 líneas de código nuevo. Pero resuelve un problema
real que ya existe: CLI y Telegram corren como procesos separados con
AgentLoops independientes. Además, habilita todo lo que viene:

```
                     MessageBus
                        │
         ┌──────────────┼──────────────┐
         │              │              │
    Sub-agentes    Canales         Servicios
    background     unificados      periódicos
         │              │              │
    spawn_background  CLI + Telegram  Cron
    (Fase 3)         (Fase 1)       Heartbeat
                     + Discord       Monitoring
                     + WhatsApp      (Fase 4)
                     (Fase 4)
```

Sin el bus, cada canal y cada feature necesita su propio mecanismo de
comunicación con el AgentLoop. Con el bus, todas hablan el mismo idioma:
`InboundMessage` → proceso → `OutboundMessage`.
