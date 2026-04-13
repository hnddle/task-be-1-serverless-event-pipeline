---
name: spec
description: Generate a structured SPEC.md from a project description. Use when starting a new project or major feature.
argument-hint: (프로젝트 설명 또는 기획서 파일 경로)
user-invocable: true
disable-model-invocation: true
allowed-tools: Read, Write, Edit, Glob, Grep, Bash(cat *)
---

# Generate SPEC.md

You are creating a technical specification document for this project.

## Input

The user's project description: $ARGUMENTS

If the argument looks like a file path, read that file first to get the project description.

## Output

Generate `./SPEC.md` with these sections:

### 1. Project Overview
- Project name, one-line description
- Problem statement
- Target users
- Target scale (data volume, concurrent users, throughput)

### 2. Tech Stack
| Category | Technology | Purpose |
|----------|-----------|---------|
| ... | ... | ... |

### 3. Architecture
- System components and responsibilities
- Data flow diagram (text-based)
- External dependencies

### 4. Core Features
Number each feature as F-001, F-002, etc.
Each feature must have:
- **Name**
- **Description**
- **Acceptance Criteria** (testable bullet points)
- **Priority**: P0 (must-have), P1 (should-have), P2 (nice-to-have)

### 5. Data Model
- Entity descriptions with key fields
- Relationships
- Estimated record counts

### 6. API Design
- Group endpoints by domain
- Each endpoint: Method, Path, Description, Auth required?

### 7. Non-Functional Requirements
- Performance, scalability, reliability, security targets

### 8. Constraints & Decisions
- Pre-made architectural decisions with rationale
- Technical constraints
- Out of scope

## Rules
- Be specific and measurable in acceptance criteria
- Include ALL technologies mentioned in the project description
- Flag any ambiguities with `[TBD]` markers for the user to resolve
- 문서는 한국어로 작성 (기술 용어 영어 허용)
