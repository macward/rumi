# Skill System Design — Rumi

## Problem Statement

Rumi tiene tools (bash, web_fetch) registrados manualmente en código. Para convertirse en Rumi, necesita:

- **Extensibilidad sin tocar core**: agregar capacidades nuevas sin modificar `cli.py` o `bot.py`
- **Composición**: combinar tools existentes en flujos de trabajo reutilizables
- **Dos niveles de complejidad**: skills simples (prompt-based, un archivo .md) y skills complejos (código Python con lógica)
- **Discovery automático**: escanear carpetas + registro manual con precedencia

## Conceptos Clave

```
Tool  = capacidad atómica (ejecutar bash, fetch URL)
Skill = conocimiento + orquestación (cuándo y cómo usar tools para una tarea)
```

Un Tool responde a "¿qué puedo hacer?". Un Skill responde a "¿cómo resuelvo este problema?".

## Arquitectura

```
┌─────────────────────────────────────────────────────────────────────┐
│                        INPUT LAYER                                  │
│              CLI / Telegram / (futuras interfaces)                   │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                        AGENT LAYER                                  │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │                    AgentLoop (existente)                      │  │
│  │              think → act → observe cycle                      │  │
│  └──────────────────────┬────────────────────────────────────────┘  │
│                         │                                           │
│                         ▼                                           │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │                  SkillManager (NUEVO)                         │  │
│  │                                                               │  │
│  │   ┌─────────────┐  ┌──────────────┐  ┌───────────────────┐   │  │
│  │   │  Discovery   │  │   Registry    │  │     Matcher       │   │  │
│  │   │  (scan dirs) │  │  (index +     │  │  (seleccionar     │   │  │
│  │   │              │  │   lifecycle)  │  │   skill por task) │   │  │
│  │   └─────────────┘  └──────────────┘  └───────────────────┘   │  │
│  └──────────────────────┬────────────────────────────────────────┘  │
│                         │                                           │
│                         ▼                                           │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │                ToolRegistry (existente)                       │  │
│  │                dispatch(tool_name, args)                      │  │
│  └───────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

## Tipos de Skill

### 1. PromptSkill (cargado desde SKILL.md)

Para skills que solo necesitan darle contexto/instrucciones al LLM.

```
skills/
└── summarize/
    └── SKILL.md
```

```markdown
---
name: summarize
description: Resumir documentos largos extrayendo puntos clave
version: 0.1.0
tags: [text, productivity]
tools_required: [bash]
---

# Summarize

Cuando el usuario pida resumir un archivo o texto largo:

1. Si es un archivo, usa `bash` para leer su contenido con `cat`
2. Divide el contenido en secciones lógicas
3. Extrae los puntos clave de cada sección
4. Presenta un resumen estructurado con:
   - Resumen ejecutivo (2-3 oraciones)
   - Puntos clave (bullets)
   - Conclusión o siguiente paso sugerido

## Restricciones
- Máximo 500 palabras en el resumen
- Mantener terminología técnica del original
- No inventar información que no esté en el texto
```

El `PromptSkill` loader parsea el frontmatter YAML y carga las instrucciones. En runtime, se inyectan en el system prompt cuando el skill es seleccionado.

### 2. CodeSkill (clase Python)

Para skills que necesitan lógica, orquestación de tools, o estado.

```python
# skills/git_review/skill.py

from rumi.skills.base import CodeSkill, SkillResult, SkillContext

class GitReviewSkill(CodeSkill):
    """Review de cambios git con análisis automático."""

    name = "git_review"
    description = "Analizar cambios en un repositorio git y generar un review"
    version = "0.1.0"
    tags = ["git", "development"]
    tools_required = ["bash"]

    async def execute(self, ctx: SkillContext) -> SkillResult:
        # 1. Obtener diff
        diff = await ctx.tools.dispatch("bash", {
            "command": "find /workspace -name '*.py' -newer /workspace/.last_review"
        })

        if not diff.success:
            return SkillResult(
                success=False,
                output="No se encontraron cambios"
            )

        # 2. Leer archivos modificados
        files_content = await ctx.tools.dispatch("bash", {
            "command": f"cat {diff.output.strip()}"
        })

        # 3. Pedir análisis al LLM
        analysis = await ctx.llm.complete(
            f"Analiza estos cambios de código y genera un review:\n{files_content.output}"
        )

        return SkillResult(
            success=True,
            output=analysis,
            metadata={"files_reviewed": diff.output.strip().split("\n")}
        )
```

## Interfaces Core

### SkillMetadata

```python
@dataclass
class SkillMetadata:
    """Metadata de un skill, parseada del frontmatter o definida en código."""
    name: str
    description: str
    version: str = "0.1.0"
    tags: list[str] = field(default_factory=list)
    tools_required: list[str] = field(default_factory=list)
    enabled: bool = True
    source: SkillSource = SkillSource.BUNDLED  # BUNDLED | USER | WORKSPACE
    path: Path | None = None  # Directorio del skill
```

### Skill (ABC)

```python
class Skill(ABC):
    """Interfaz base para todos los skills."""

    @property
    @abstractmethod
    def metadata(self) -> SkillMetadata: ...

    @abstractmethod
    async def execute(self, ctx: SkillContext) -> SkillResult: ...

    def can_handle(self, query: str) -> float:
        """Score de 0.0 a 1.0 indicando qué tan relevante es este skill
        para una query. Implementación default usa keyword matching
        contra description + tags. Code skills pueden override con
        lógica más sofisticada."""
        ...
```

### SkillContext

```python
@dataclass
class SkillContext:
    """Contexto inyectado a un skill durante ejecución."""
    tools: ToolRegistry          # Acceso a tools registrados
    session: SessionState        # Estado de la sesión actual
    chat_id: str                 # ID de la conversación
    user_message: str            # Mensaje original del usuario
    llm: LLMClient | None       # Cliente LLM (para CodeSkills que necesiten)
    config: dict[str, Any]       # Config específica del skill
```

### SkillResult

```python
@dataclass
class SkillResult:
    """Resultado de ejecutar un skill."""
    success: bool
    output: str
    error: str | None = None
    metadata: dict[str, Any] | None = None
    prompt_injection: str | None = None  # Instrucciones extra para el system prompt
```

## SkillManager

Componente central que gestiona el lifecycle completo.

```python
class SkillManager:
    """Gestión de skills: discovery, registro, matching, ejecución."""

    def __init__(self, config: SkillsConfig): ...

    # === Discovery ===
    def discover(self) -> list[SkillMetadata]:
        """Escanea directorios de skills y retorna metadata."""

    def load_skill(self, path: Path) -> Skill:
        """Carga un skill desde su directorio.
        Detecta tipo (SKILL.md → PromptSkill, skill.py → CodeSkill)."""

    # === Registry ===
    def register(self, skill: Skill) -> None:
        """Registra un skill. Respeta precedencia si hay conflicto de nombre."""

    def unregister(self, name: str) -> None: ...

    def get(self, name: str) -> Skill | None: ...

    def list_skills(self) -> list[SkillMetadata]: ...

    def enable(self, name: str) -> None: ...

    def disable(self, name: str) -> None: ...

    # === Matching ===
    def match(self, query: str) -> list[tuple[Skill, float]]:
        """Retorna skills ordenados por relevancia para una query.
        Usa can_handle() de cada skill + keyword matching."""

    def get_available_skills_prompt(self) -> str:
        """Genera el bloque <available_skills> para el system prompt.
        Solo incluye name + description (no instrucciones completas)."""

    # === Execution ===
    async def execute(self, name: str, ctx: SkillContext) -> SkillResult:
        """Ejecuta un skill por nombre con el contexto dado."""

    # === Lifecycle ===
    def refresh(self) -> None:
        """Re-escanea directorios y actualiza registry."""
```

## Discovery y Precedencia

Skills se cargan desde múltiples ubicaciones con precedencia:

```
Prioridad ALTA
  │
  ├── 1. Workspace skills:  ~/.rumi/workspace/{agent}/skills/
  │      (skills específicos de un agente/proyecto)
  │
  ├── 2. User skills:       ~/.rumi/skills/
  │      (skills personales del usuario)
  │
  ├── 3. Bundled skills:    rumi/skills/bundled/
  │      (skills incluidos con la instalación)
  │
Prioridad BAJA
```

Si dos skills tienen el mismo `name`, gana el de mayor prioridad. Esto permite override sin modificar los bundled.

### Estructura de directorio de un Skill

```
skills/
├── summarize/              # PromptSkill (solo SKILL.md)
│   └── SKILL.md
│
├── git_review/             # CodeSkill (Python)
│   ├── SKILL.md            # Metadata + descripción (requerido)
│   ├── skill.py            # Implementación (presencia indica CodeSkill)
│   └── requirements.txt    # Dependencias opcionales
│
└── web_research/           # CodeSkill con archivos auxiliares
    ├── SKILL.md
    ├── skill.py
    ├── prompts/            # Templates de prompts
    │   └── research.txt
    └── tests/
        └── test_skill.py
```

**Regla de detección:**
- Si existe `skill.py` → CodeSkill (importar clase)
- Si solo existe `SKILL.md` → PromptSkill (parsear markdown)

## Integración con AgentLoop

### Opción elegida: Skill como contexto del prompt

El SkillManager no reemplaza el AgentLoop — lo **enriquece**. El flujo modificado:

```
User message
    │
    ▼
┌──────────────────────────────────────────────┐
│ 1. SkillManager.get_available_skills_prompt() │
│    → Genera lista compacta de skills          │
│    → Se inyecta en system prompt              │
│    (~25 tokens por skill: solo name+desc)     │
└──────────────────────┬───────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────┐
│ 2. AgentLoop.run() — Turn N (think)           │
│    → LLM ve <available_skills> en prompt      │
│    → LLM decide si necesita un skill          │
│    → Si sí: tool_call "use_skill"             │
└──────────────────────┬───────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────────┐
│ 3. ToolRegistry.dispatch("use_skill", args)                  │
│    → SkillExecutorTool recibe la llamada                     │
│                                                              │
│    ┌─ PromptSkill ──────────────────────────────────────┐    │
│    │ Carga SKILL.md completo (instrucciones)             │    │
│    │ Retorna instrucciones como ToolResult.output         │    │
│    │ NO hace llamada LLM adicional                       │    │
│    │ El AgentLoop las mete como mensaje role="tool"      │    │
│    └─────────────────────────────────────────────────────┘    │
│                                                              │
│    ┌─ CodeSkill ────────────────────────────────────────┐    │
│    │ Ejecuta skill.execute(ctx) con lógica Python        │    │
│    │ Puede orquestar múltiples tools vía ctx.tools       │    │
│    │ Puede llamar al LLM vía ctx.llm                     │    │
│    │ Retorna SkillResult con output procesado            │    │
│    └─────────────────────────────────────────────────────┘    │
└──────────────────────────┬───────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────┐
│ 4. AgentLoop — Turn N+1 (observe → think)                    │
│                                                              │
│    PromptSkill: LLM recibe instrucciones como tool result    │
│    y las SIGUE en este turn (ejecuta tools según las         │
│    instrucciones del skill). Costo: 1 turn extra del loop.   │
│                                                              │
│    CodeSkill: LLM recibe el output ya procesado y formula    │
│    la respuesta final al usuario.                            │
│                                                              │
│    → Continúa ciclo think→act→observe hasta COMPLETE         │
└──────────────────────────────────────────────────────────────┘
```

### SkillExecutorTool

Bridge entre ToolRegistry y SkillManager. Se registra como un Tool más:

```python
class SkillExecutorTool(Tool):
    """Tool que permite al LLM invocar skills."""

    def __init__(self, skill_manager: SkillManager): ...

    @property
    def name(self) -> str:
        return "use_skill"

    @property
    def description(self) -> str:
        return "Execute a skill by name. Check <available_skills> for options."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "skill_name": {
                    "type": "string",
                    "description": "Name of the skill to execute"
                },
                "input": {
                    "type": "string",
                    "description": "Input or context for the skill"
                }
            },
            "required": ["skill_name"]
        }

    async def execute(self, skill_name: str, input: str = "", **kwargs) -> ToolResult:
        ctx = SkillContext(...)
        result = await self.skill_manager.execute(skill_name, ctx)
        return ToolResult(
            success=result.success,
            output=result.output,
            error=result.error
        )
```

### System Prompt Modificado

```python
SYSTEM_PROMPT = """You are Rumi, a versatile personal assistant...

You have access to the following tools:
{tools_description}

{available_skills_block}

When a task matches a skill's description, use the `use_skill` tool to invoke it.
For simple tasks that only need a single tool, use the tool directly.
"""
```

Donde `available_skills_block` se ve así:

```xml
<available_skills>
<skill>
  <name>summarize</name>
  <description>Resumir documentos largos extrayendo puntos clave</description>
</skill>
<skill>
  <name>git_review</name>
  <description>Analizar cambios en un repositorio git y generar un review</description>
</skill>
</available_skills>
```

## Config

```python
@dataclass
class SkillsConfig:
    """Configuración del sistema de skills."""
    skills_dirs: list[Path] = field(default_factory=lambda: [
        Path.home() / ".rumi" / "skills",
    ])
    bundled_dir: Path | None = None  # Se auto-detecta del paquete
    enabled_skills: list[str] | None = None   # None = todos habilitados
    disabled_skills: list[str] = field(default_factory=list)
    max_skills_in_prompt: int = 20  # Límite para controlar tokens
```

En `~/.rumi/rumi.json`:

```json
{
  "skills": {
    "dirs": ["~/.rumi/skills", "~/projects/my-skills"],
    "disabled": ["git_review"],
    "settings": {
      "summarize": {
        "max_words": 300
      }
    }
  }
}
```

## Estructura del Módulo en el Proyecto

```
src/rumi/
├── skills/                  # NUEVO módulo
│   ├── __init__.py          # Exports: SkillManager, Skill, SkillResult...
│   ├── base.py              # Skill ABC, SkillMetadata, SkillResult, SkillContext
│   ├── manager.py           # SkillManager (discovery, registry, matching)
│   ├── prompt_skill.py      # PromptSkill (carga SKILL.md)
│   ├── code_skill.py        # CodeSkill base + loader
│   ├── executor_tool.py     # SkillExecutorTool (bridge a ToolRegistry)
│   ├── parser.py            # Parser de SKILL.md (frontmatter + body)
│   └── bundled/             # Skills incluidos
│       ├── summarize/
│       │   └── SKILL.md
│       └── file_ops/
│           └── SKILL.md
├── agent/                   # EXISTENTE (modificar prompt.py)
├── tools/                   # EXISTENTE (sin cambios)
├── sandbox/                 # EXISTENTE (sin cambios)
└── session/                 # EXISTENTE (sin cambios)
```

## Impacto en Tokens

Cada skill en `<available_skills>` agrega ~20-30 tokens (name + description).
Las instrucciones completas solo se cargan cuando el skill se invoca.

| Skills activos | Tokens en prompt | Impacto |
|---------------|-----------------|---------|
| 5             | ~125            | Mínimo  |
| 20            | ~500            | Aceptable |
| 50            | ~1,250          | Límite recomendado |

`max_skills_in_prompt` en config actúa como safety net.

## Fases de Implementación

### Fase 1: Core mínimo
- [ ] `base.py` — Skill, SkillMetadata, SkillResult, SkillContext
- [ ] `parser.py` — Parser de SKILL.md con frontmatter
- [ ] `prompt_skill.py` — PromptSkill que carga desde .md
- [ ] `manager.py` — SkillManager con discover() y register()
- [ ] `executor_tool.py` — SkillExecutorTool
- [ ] Modificar `prompt.py` para incluir available_skills
- [ ] 1-2 bundled PromptSkills de ejemplo

### Fase 2: CodeSkills + Config
- [ ] `code_skill.py` — Loader de skills Python
- [ ] Config desde `rumi.json` (enable/disable, settings)
- [ ] Precedencia de directorios
- [ ] Tests completos

### Fase 3: Matching inteligente
- [ ] `can_handle()` con scoring
- [ ] Match programático antes de delegar al LLM
- [ ] Cache/snapshot de skills (como OpenClaw)

### Fase 4: Ecosystem
- [ ] CLI para gestión (`rumi skills list|enable|disable|create`)
- [ ] Template generator para nuevos skills
- [ ] Validación de dependencias (tools_required)

---

## Decisiones de Arquitectura

### ADR-011: Skills como capa sobre Tools, no reemplazo

**Status**: Propuesto

**Decisión**: Skills no reemplazan Tools. Un Skill usa Tools vía ToolRegistry, nunca ejecuta código directamente fuera del sandbox.

**Rationale**:
- Mantiene las garantías de seguridad existentes (sandbox, allowlist)
- Un Skill solo amplifica lo que los Tools ya pueden hacer
- Separación clara: Tools = capacidades, Skills = estrategias

### ADR-012: Detección de tipo por presencia de skill.py

**Status**: Propuesto

**Decisión**: Si un directorio de skill contiene `skill.py`, se carga como CodeSkill. Si solo tiene `SKILL.md`, se carga como PromptSkill.

**Rationale**:
- Convención simple sin necesidad de flags en config
- Compatible con el modelo de OpenClaw (solo .md)
- Permite evolucionar un PromptSkill a CodeSkill agregando skill.py

### ADR-013: SkillExecutorTool como bridge

**Status**: Propuesto

**Decisión**: Los skills se invocan a través de un Tool (`use_skill`), no mediante un mecanismo separado.

**Rationale**:
- Reutiliza todo el flujo existente del AgentLoop (no requiere cambios al loop)
- El LLM ya sabe usar tools — `use_skill` es solo otro tool más
- Logging, circuit breakers, error handling se aplican automáticamente
- Mínimo impacto en código existente

### ADR-014: Discovery con precedencia de directorios

**Status**: Propuesto

**Decisión**: workspace > user > bundled. Mismo nombre = gana mayor prioridad.

**Rationale**:
- Permite override limpio sin modificar bundled skills
- Mismo modelo probado en OpenClaw
- Workspace-specific skills para proyectos con necesidades particulares

### ADR-015: PromptSkill retorna instrucciones como ToolResult, no inyecta al system prompt

**Status**: Aceptado

**Contexto**: ¿Cómo recibe el LLM las instrucciones completas de un PromptSkill cuando se invoca `use_skill`?

**Opciones consideradas**:
1. Inyectar instrucciones en el system prompt y hacer otra llamada LLM
2. Retornar instrucciones como output del tool call
3. Crear un mecanismo de "prompt append" separado

**Decisión**: Opción 2. El `PromptSkill.execute()` carga el SKILL.md completo y lo retorna como `ToolResult.output`. El AgentLoop lo inserta como mensaje `role="tool"` (flujo estándar). El LLM recibe las instrucciones en el siguiente turn y las ejecuta.

**Rationale**:
- Zero cambios al AgentLoop — usa el flujo existente de tool results
- El LLM ya sabe interpretar tool results y actuar en consecuencia
- No requiere manipulación del system prompt en runtime
- Costo: 1 turn extra del loop (aceptable dado max_turns=10)

**Consecuencias**:
- Las instrucciones del skill consumen tokens de contexto como cualquier tool result
- Skills con instrucciones muy largas podrían necesitar truncado
- El LLM podría no seguir todas las instrucciones al pie — mitigado con instrucciones claras y concisas en los SKILL.md

### ADR-016: Usar python-frontmatter para parsing de SKILL.md

**Status**: Aceptado

**Contexto**: Los SKILL.md usan frontmatter YAML (`---` delimiters) + cuerpo markdown. ¿Parser manual o dependencia?

**Opciones consideradas**:
1. `python-frontmatter` — librería madura, bien testeada
2. Parser manual con `yaml` stdlib + split por `---`
3. Formato diferente (TOML, JSON header)

**Decisión**: Opción 1. Usar `python-frontmatter` (dependencia: `python-frontmatter` + `pyyaml`).

**Rationale**:
- Librería mínima (~200 líneas), sin dependencias transitivas pesadas
- Maneja edge cases que un parser manual podría fallar (encoding, YAML multiline, etc.)
- Formato idéntico al de OpenClaw — compatibilidad directa con el ecosistema existente
- `pyyaml` ya es dependencia transitiva común en el ecosistema Python

**Consecuencias**:
- 1 dependencia nueva en `pyproject.toml`: `python-frontmatter >= 1.0`
- Si en algún momento se quiere eliminar, el parser manual es trivial como fallback

### ADR-017: CodeSkills cargados via importlib con ejecución trust-on-install

**Status**: Aceptado

**Contexto**: Los CodeSkills son archivos Python arbitrarios (`skill.py`). Importarlos con `importlib` ejecuta código en el proceso principal.

**Opciones consideradas**:
1. `importlib.import_module()` — ejecución directa en proceso
2. `subprocess` — ejecutar skill.py en proceso separado
3. Sandbox con `RestrictedPython` o similar
4. Solo PromptSkills, sin CodeSkills

**Decisión**: Opción 1 con modelo **trust-on-install** (misma confianza que `pip install`).

**Rationale**:
- Los CodeSkills los instala el usuario en su propia máquina — mismo trust que cualquier paquete pip
- `subprocess` añade complejidad de serialización y pierde acceso tipado a ToolRegistry
- `RestrictedPython` es frágil y limita funcionalidad legítima
- La barrera real de seguridad ya existe: CodeSkills acceden al sandbox SOLO vía `ctx.tools.dispatch()`

**Restricciones de seguridad (por convención, enforceable en Fase 3+)**:
- CodeSkills DEBEN operar a través de `ctx.tools` y `ctx.llm`, no acceso directo a filesystem/red
- El `SkillManager` valida que `skill.py` exponga exactamente una clase que herede de `CodeSkill`
- Bundled skills son code-reviewed. User/workspace skills son responsabilidad del usuario
- Futuro: lint rules o AST check para detectar imports peligrosos (`os.system`, `subprocess`, `socket`)

**Consecuencias**:
- Un CodeSkill malicioso en `~/.rumi/skills/` podría ejecutar código arbitrario
- Mitigación: warning en docs, validación básica al cargar, logs de qué skills se importan
- Alineado con el modelo de seguridad de OpenClaw (trust del usuario en skills locales)

### ADR-018: CodeSkills reutilizan el LLM client del AgentLoop via Protocol

**Status**: Aceptado

**Contexto**: Los CodeSkills pueden necesitar llamar al LLM directamente (análisis, generación). ¿Crear instancia nueva o reutilizar la existente?

**Opciones consideradas**:
1. Pasar referencia directa a `AsyncGroq` client
2. Crear nuevo client por skill execution
3. Interfaz abstracta (`Protocol`) que wrappea el client existente

**Decisión**: Opción 3. Definir un `LLMClient` Protocol y que el AgentLoop pase un wrapper de su instancia.

```python
from typing import Protocol

class LLMClient(Protocol):
    """Interfaz mínima para que CodeSkills accedan al LLM."""

    async def complete(self, prompt: str, system: str | None = None) -> str:
        """Completar un prompt. Retorna solo el texto de respuesta."""
        ...

class GroqLLMClient:
    """Wrapper concreto que adapta AsyncGroq al Protocol."""

    def __init__(self, client: AsyncGroq, model: str):
        self._client = client
        self._model = model

    async def complete(self, prompt: str, system: str | None = None) -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        response = await self._client.chat.completions.create(
            model=self._model,
            messages=messages,
        )
        return response.choices[0].message.content or ""
```

**Rationale**:
- CodeSkills no dependen de Groq — si se cambia a OpenAI/Anthropic/local, solo cambia el wrapper
- Reutiliza API key, rate limits y configuración del AgentLoop
- Protocol permite testing fácil (mock del LLM en tests)
- Interfaz mínima: solo `complete()` — un CodeSkill no necesita manejar tools ni historial

**Consecuencias**:
- El AgentLoop necesita exponer su client wrapeado al construir el SkillContext
- Si un CodeSkill necesita streaming o tool calling propio, la interfaz se puede extender después
- Un CodeSkill que abuse del LLM (muchas llamadas) consumirá tokens del mismo budget — monitoreable via logging existente
