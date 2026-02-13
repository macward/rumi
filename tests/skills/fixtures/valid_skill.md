---
name: summarize
description: Summarize documents extracting key points
version: 1.0.0
tags: [text, productivity]
tools_required: [bash]
---

# Summarize

When the user asks to summarize a file or text:

1. If it's a file, use `bash` to read its content with `cat`
2. Divide the content into logical sections
3. Extract key points from each section
4. Present a structured summary with:
   - Executive summary (2-3 sentences)
   - Key points (bullets)
   - Conclusion or suggested next step

## Constraints
- Maximum 500 words in summary
- Keep technical terminology from the original
- Don't invent information not in the text
