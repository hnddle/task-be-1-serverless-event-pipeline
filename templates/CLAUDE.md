# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

{{PROJECT_NAME}} — {{ONE_LINE_DESCRIPTION}}
현재 기획/설계 단계이며 코드 구현 전이다. SPEC.md와 PLAN.md에 따라 Phase 0부터 순차 구현 예정.

- `CONCEPT.md` — 서비스 기획서
- `SPEC.md` — 기술 명세서 (단일 진실 공급원)
- `PLAN.md` — 구현 계획서

## Architecture (핵심 흐름)

```
{{ARCHITECTURE_DIAGRAM — SPEC.md 기반으로 채우기}}
```

## Tech Stack

| Layer | Technology |
|-------|-----------|
| {{LAYER}} | {{TECHNOLOGY}} |

## Development Commands

```bash
# 프로젝트에 맞게 수정
{{DEV_COMMANDS}}
```

## Git Workflow

- **Gitflow**: master(프로덕션) / develop(통합) / feature·release·hotfix 브랜치
- **master 직접 커밋 금지** (PreToolUse hook으로 자동 차단)
- **커밋 메시지**: Conventional Commits, **한글로 작성** (기술 용어는 영어 허용)
  ```
  {type}({scope}): {한글 subject}
  ```
- 상세 규칙: @.claude/rules/git-workflow.md

## Key Rules

@.claude/rules/code-style.md
@.claude/rules/git-workflow.md
@.claude/rules/testing.md
@.claude/rules/security.md

## Implementation Tracking

- Current plan: @PLAN.md
- Mark completed steps by changing `[ ]` to `[x]`
- 구현 시 `/step X-Y` 스킬로 자동 실행, `/ship`으로 커밋+푸시

## Notes

- 문서 기본 언어: 한국어
- 서비스 언어: 한국어 전용
