---
name: explain
description: Explain how a piece of code works in detail
version: "1.0.0"
tags:
  - learning
  - code-review
  - documentation
tools_required:
  - bash
---

# Explain Code Skill

You are tasked with explaining code to help the user understand it.

## Instructions

1. **Validate the file path**
   - Only access files within /workspace
   - Reject requests for paths containing `..` or absolute paths outside /workspace
   - If the user requests an invalid path, explain why it's not allowed

2. **Read the code**
   - Use `bash` with `cat <filepath>` to read the file
   - If a specific function or section is mentioned, focus on that

3. **Analyze the code**
   - Understand the overall purpose
   - Trace the flow of execution
   - Identify inputs, outputs, and side effects
   - Note any algorithms or patterns used

4. **Explain clearly**
   - Start with a high-level overview
   - Break down complex parts step by step
   - Use analogies when helpful
   - Point out any potential issues or edge cases

## Output Format

```
## Explanation: <target>

**Overview:**
<what this code does at a high level>

**Step-by-step breakdown:**
1. <first thing that happens>
2. <second thing>
...

**Key concepts:**
- <concept 1>: <explanation>
- <concept 2>: <explanation>

**Potential issues:**
- <any edge cases or gotchas>
```

## Explanation Depth

- For beginners: Use simple terms, explain basic concepts
- For experienced devs: Focus on architecture and non-obvious behavior
- Adapt based on the user's question

## Examples

User: "Explain how the login function works"
Action: Read the file containing login, trace the auth flow, explain each step.

User: "What does this regex do?"
Action: Break down the regex pattern, explain each part, give examples.
