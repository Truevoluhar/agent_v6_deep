# File Analysis

Use this skill when the user asks for targeted inspection of uploaded files, large documents, or mixed project artifacts.

Workflow:
- Identify the file types and sizes before loading them deeply.
- Prefer summaries, indexes, and extracted artifacts over dumping raw file contents into the response.
- Write durable outputs to `/workspace/analysis/` with clear names.
- If inputs are large, inspect selectively and record assumptions or skipped sections.
- When helpful, leave a short Markdown report describing findings, evidence, and next steps.

