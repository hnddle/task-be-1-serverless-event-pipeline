---
name: make-plan
description: Generate PLAN.md from SPEC.md with numbered implementation steps. Use after SPEC.md is finalized.
user-invocable: true
disable-model-invocation: true
allowed-tools: Read, Write, Edit, Glob, Grep
---

# Generate PLAN.md

## Instructions

1. Read `./SPEC.md` thoroughly
2. Generate `./PLAN.md` with a phased implementation plan

## Plan Structure

```markdown
# Implementation Plan

## Overview
- Total Phases: N
- Total Steps: M
- Estimated scope: [brief summary]

## Phase 0: 프로젝트 초기화 및 인프라
(Docker, DB, 기본 프로젝트 뼈대, CI 설정 등)

## Phase 1: [Phase Title]
Description of what this phase accomplishes.

### Step 1-1: [Step Title]
**Objective:** One sentence.
**Feature Branch:** `feature/step-1-1-short-desc`
**Files to Create/Modify:**
- `path/to/file.py` — What this file does
**Dependencies:** None | Step X-Y
**Implementation Details:**
- Key decisions and approach
- References to SPEC.md features (F-001, etc.)
**Acceptance Criteria:**
- [ ] Criterion 1
- [ ] Criterion 2
- [ ] Tests pass

(repeat for each step)
```

## Rules
1. Each step = one atomic coding session (15-45 min for Claude to implement)
2. Steps are ordered by dependency — no step references a later step
3. Every file in the project appears in exactly one step
4. Test files are in the same step as the code they test (각 Phase에 테스트 통합)
5. Reference SPEC.md feature IDs where applicable
6. Include infrastructure steps (Docker, CI, configs) in Phase 0
7. Security items should be distributed across relevant phases (보안 항목 분산 배치)
8. 모노레포 디렉토리 구조를 상단에 포함
