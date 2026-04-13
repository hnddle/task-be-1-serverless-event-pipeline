---
name: step
description: Execute a specific step from PLAN.md. Usage /step 1-1
argument-hint: (step-number e.g. 1-1)
user-invocable: true
disable-model-invocation: true
allowed-tools: Read, Write, Edit, Glob, Grep, Bash(git *), Bash(python *), Bash(pip *), Bash(uv *), Bash(pytest *), Bash(ruff *), Bash(mypy *), Bash(mkdir *), Bash(ls *), Bash(cat *), Bash(alembic *), Bash(celery *), Bash(npm *), Bash(npx *), Bash(node *), Bash(docker *), Bash(docker compose *)
effort: high
---

# Execute Plan Step $ARGUMENTS

## Procedure

### 1. Load Context
- Read `./PLAN.md` and find **Step $0**
- Read `./SPEC.md` for referenced features
- Read `./CLAUDE.md` for project conventions

### 2. Validate Prerequisites
- Check that all dependency steps (listed in "Dependencies") are completed
  - A step is completed if its acceptance criteria checkboxes are checked `[x]` in PLAN.md
- If dependencies are NOT met, stop and inform the user which steps must be completed first

### 3. Create Feature Branch
- Get the feature branch name from the step definition
- Run: `git checkout develop && git checkout -b feature/step-$0-{description}`
- If branch already exists, just check it out

### 4. Implement
- Follow the step's "Implementation Details" precisely
- Create/modify only the files listed in "Files to Create/Modify"
- Follow all rules in .claude/rules/
- Write clean, production-ready code with type hints
- Write tests for all public functions

### 5. Verify
- Run linter and fix any issues
- Run formatter
- Run tests on relevant test files (if tests exist)
- Run type checker if set up
- Check each acceptance criterion manually

### 6. Update PLAN.md
- Mark completed acceptance criteria: change `[ ]` to `[x]`
- Do NOT modify any other steps

### 7. Report
After completion, output:
```
## Step $0 Complete

**Branch:** feature/step-$0-{description}
**Files Changed:**
- list of files created or modified

**Acceptance Criteria:**
- [x] criterion 1
- [x] criterion 2

**Next Step:** Step {next step number} — {title}
Ready to commit? Use /ship
```
