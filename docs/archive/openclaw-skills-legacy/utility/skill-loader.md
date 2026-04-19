# Skill: Skill Loader

## Purpose
Load, validate, and register SKILL.md files from the skills directory for agent use. Supports hot-reload and filtering by category.

## Triggers
- When the agent starts and needs to load available skills
- When user requests skill list or skill reload
- When new skills are added and need registration
- When filtering skills by category (e.g., execution, analysis)

## Inputs
- `action`: string — "load", "reload", "list", or "validate"
- `categories`: string[] — Filter by category (e.g., ["execution", "risk"])
- `skill_names`: string[] — Specific skills to load (optional)
- `base_path`: string — Skills directory path (default: openclaw/skills)

## Outputs
- `skills`: object[] — Loaded skills with name, purpose, triggers, inputs
- `count`: number — Number of skills loaded or listed
- `errors`: object[] — Validation errors per skill file
- `metadata`: object — Base path, categories, load time

## Steps
1. Resolve base_path; scan for SKILL.md files recursively
2. For "load"/"reload": parse each SKILL.md (Purpose, Triggers, Inputs, Outputs, Steps)
3. Validate required sections present; record errors
4. Filter by categories (directory name) or skill_names if specified
5. Build skill registry: name -> {purpose, triggers, inputs, outputs, steps}
6. For "list": return names and categories only
7. For "validate": return errors without loading
8. Cache parsed skills; invalidate on reload
9. Return skills, count, errors, metadata

## Example
```
Input: action="load", categories=["execution", "risk"]
Output: {
  skills: [{name: "order-placer", purpose: "Place orders...", triggers: [...]}, ...],
  count: 8,
  errors: [],
  metadata: {base_path: "openclaw/skills", categories: ["execution","risk"], loaded_at: "2025-03-03T15:00:00Z"}
}
```
