"""Tests for prompt builder."""

from miniclaw.agent.prompt import build_system_prompt


class TestBuildSystemPrompt:
    """Tests for build_system_prompt function."""

    def test_no_memory_block(self):
        """Prompt without memory block doesn't include memory section."""
        prompt = build_system_prompt(tools_schema=[])
        assert "<memory>" not in prompt
        assert "Lo que sabés del usuario:" not in prompt

    def test_empty_memory_block(self):
        """Empty memory block string doesn't add anything."""
        prompt = build_system_prompt(tools_schema=[], memory_block="")
        assert "<memory>" not in prompt

    def test_whitespace_memory_block(self):
        """Whitespace-only memory block doesn't add anything."""
        prompt = build_system_prompt(tools_schema=[], memory_block="   \n  ")
        assert "<memory>" not in prompt

    def test_memory_block_included(self):
        """Memory block is appended to prompt."""
        memory = """<memory>
Lo que sabés del usuario:
- nombre: Lucas
</memory>"""
        prompt = build_system_prompt(tools_schema=[], memory_block=memory)
        assert "<memory>" in prompt
        assert "- nombre: Lucas" in prompt
        assert "</memory>" in prompt

    def test_memory_block_at_end(self):
        """Memory block is added at the end of the prompt."""
        memory = "<memory>\ntest\n</memory>"
        prompt = build_system_prompt(tools_schema=[], memory_block=memory)
        assert prompt.endswith("</memory>")

    def test_all_sections_combined(self):
        """All sections (tools, skills, memory) can be combined."""
        tools = [
            {
                "function": {
                    "name": "bash",
                    "description": "Run a bash command",
                }
            }
        ]
        skills = "<available-skills>\n- test_skill\n</available-skills>"
        memory = "<memory>\n- nombre: Lucas\n</memory>"

        prompt = build_system_prompt(
            tools_schema=tools,
            available_skills_block=skills,
            memory_block=memory,
        )

        assert "bash" in prompt
        assert "<available-skills>" in prompt
        assert "<memory>" in prompt
