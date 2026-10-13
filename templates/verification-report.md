# Verification — <change name>

Stage 5. One line per acceptance criterion from the delta specs. The gate
enforces at least one `- PASS` and zero `- FAIL`; it does **not** check that you
covered every criterion. That part is on you.

Spec: `openspec/changes/<change>/specs/<capability>/spec.md`
Command: `<how the suite was run>` → `<result>`

- PASS <criterion>: <what was observed> (<test or evidence>)
- PASS <criterion>: <what was observed> (<test or evidence>)

Use `- FAIL <criterion>: <what broke>` for a failure. Any FAIL blocks the gate;
fix and re-verify rather than deleting the line.
