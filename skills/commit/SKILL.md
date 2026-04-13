---
name: commit
description: Stage and commit changes with conventional commit message (한글). Auto-detects commit type.
user-invocable: true
disable-model-invocation: true
allowed-tools: Bash(git *)
---

# Gitflow Commit

## Procedure

### 1. Analyze Current State
- Run `git status` to see all changes
- Run `git diff` to understand what changed
- Run `git branch --show-current` to get current branch name

### 2. Determine Commit Prefix
Based on the current branch name and change type:
- `feature/*` → `feat:` (새 기능) or `fix:` / `refactor:` / `test:` / `docs:` as appropriate
- `release/*` → `release:`
- `hotfix/*` → `fix:`
- `develop` → `chore:` or `refactor:` (pick the most appropriate)
- `master` → **STOP** — never commit directly to master

### 3. Generate Commit Message
- Analyze the diff to understand WHAT changed
- Write a concise message: `{type}({scope}): {한글 subject}`
- subject는 **한글**로 작성 (기술 용어는 영어 허용)
- Keep the subject under 50 characters
- Add scope if the change targets a specific area (e.g., `feat(auth):`, `fix(chat):`)
- If the change is complex, add a blank line followed by body text

### 4. Stage and Commit
```bash
git add -A
git commit -m "{type}({scope}): {subject}

Co-Authored-By: Claude <noreply@anthropic.com>"
```

### 5. Show Result
Display the commit hash, message, and changed files count.

If the user provided arguments, use them as additional context for the commit message:
$ARGUMENTS
