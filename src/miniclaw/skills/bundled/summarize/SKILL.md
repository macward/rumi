---
name: summarize
description: Summarize the contents of a file or multiple files
version: "1.0.0"
tags:
  - documentation
  - analysis
tools_required:
  - bash
---

# Summarize Skill

You are tasked with summarizing file contents for the user.

## Instructions

1. **Validate the file path**
   - Only access files within /workspace
   - Reject requests for paths containing `..` or absolute paths outside /workspace
   - If the user requests an invalid path, explain why it's not allowed

2. **Read the target file(s)**
   - Use `bash` with `cat <filepath>` to read the file contents
   - If multiple files are specified, read each one

3. **Analyze the content**
   - Identify the main purpose of the file
   - Note key sections, functions, classes, or data structures
   - Understand the overall structure

4. **Generate a summary**
   - Start with a one-line description of what the file does
   - List the main components (functions, classes, sections)
   - Highlight any important patterns or dependencies
   - Keep it concise but informative

## Output Format

```
## Summary: <filename>

**Purpose:** <one-line description>

**Key Components:**
- <component 1>: <brief description>
- <component 2>: <brief description>

**Notes:**
- <any important observations>
```

## Examples

User: "Summarize the main.py file"
Action: Read main.py with bash, then provide structured summary.

User: "Give me an overview of all files in src/"
Action: List files, read each one, provide summaries.
