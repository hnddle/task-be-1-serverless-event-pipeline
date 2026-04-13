---
name: ship
description: 변경 내용을 분석하여 브랜치 분류 → 커밋 메시지 자동 생성(한글) → 커밋 → 푸시까지 한 번에 수행. Usage /ship 또는 /ship "추가 설명"
argument-hint: (선택) 커밋에 포함할 추가 컨텍스트
user-invocable: true
disable-model-invocation: true
allowed-tools: Read, Glob, Grep, Bash(git *)
---

# /ship — 자동 분류 · 커밋 · 푸시

변경 내용을 분석하여 적절한 브랜치를 생성하고, 한글 커밋 메시지를 작성한 뒤, 커밋 및 푸시까지 자동 수행한다.

## 실행 절차

### 1. 현재 상태 파악

```bash
git status
git diff --stat
git diff --staged --stat
git diff
git diff --staged
git branch --show-current
```

모든 변경 내용(staged + unstaged + untracked)을 분석한다.

### 2. 변경 유형 자동 분류

변경된 파일과 내용을 분석하여 가장 적절한 커밋 type을 결정한다:

| 조건 | type | 설명 |
|------|------|------|
| 새 파일/기능 추가 | `feat` | 새로운 기능 |
| 버그 관련 수정 | `fix` | 버그 수정 |
| .md 파일만 변경 | `docs` | 문서 변경 |
| 포매팅/공백/세미콜론만 변경 | `style` | 포매팅 변경 |
| 기능 변경 없는 코드 구조 개선 | `refactor` | 리팩토링 |
| 성능 관련 개선 | `perf` | 성능 개선 |
| 테스트 파일만 변경 | `test` | 테스트 |
| 설정/빌드/의존성 변경 | `chore` | 기타 변경 |
| CI 설정 변경 | `ci` | CI 변경 |

복수 type에 해당하면 가장 주요한 변경 기준으로 선택한다.

### 3. 브랜치 판단 및 생성

**현재 브랜치가 이미 적절한 feature/hotfix/release 브랜치인 경우:**
- 그대로 사용한다.

**현재 브랜치가 develop인 경우:**
- 변경 type에 따라 feature 브랜치를 자동 생성한다.
- 브랜치명: `feature/{type}-{변경-요약-영문-kebab-case}`
- 예: `feature/docs-add-api-spec`, `feature/feat-auth-module`

**현재 브랜치가 master(또는 main)인 경우:**
- **경고**: master에서 직접 작업하면 안 됩니다.
- hotfix가 아닌 경우 → develop으로 이동 후 feature 브랜치 생성
- hotfix인 경우 → `hotfix/{요약}` 브랜치 생성

```bash
# develop에서 feature 브랜치 생성 예시
git checkout -b feature/{type}-{description}
```

### 4. 커밋 메시지 생성 (한글)

**형식:**
```
{type}({scope}): {한글 subject}

{한글 body — 변경 이유가 명확하지 않은 경우에만}

Co-Authored-By: Claude <noreply@anthropic.com>
```

**규칙:**
- subject는 **한글**로 작성 (기술 용어는 영어 허용)
- subject 50자 이내, 마침표 없음, 명령형
- scope는 변경된 주요 영역에서 추출 (선택)
- body는 변경 이유가 명확하지 않은 경우에만 작성
- 사용자가 $ARGUMENTS로 추가 컨텍스트를 제공한 경우 반영

**예시:**
```
feat(auth): 비회원 세션 생성 및 JWT 인증 구현
docs: 프로젝트 기술 명세서 및 구현 계획서 추가
fix(chat): SSE 연결 끊김 시 재연결 로직 수정
chore: Docker Compose 개발 환경 설정 추가
```

### 5. 사용자 확인

커밋 전에 아래 내용을 사용자에게 보여주고 확인을 받는다:

```
## /ship 요약

**브랜치:** {현재 또는 새로 생성할 브랜치명}
**커밋 메시지:**
{생성된 커밋 메시지 전문}

**변경 파일:**
- {파일 목록}

진행할까요?
```

### 6. 스테이징 · 커밋 · 푸시

사용자 확인 후:

```bash
# 모든 변경 사항 스테이징
git add -A

# 커밋
git commit -m "{커밋 메시지}"

# 푸시 (새 브랜치면 -u 포함)
git push -u origin {브랜치명}
```

### 7. 결과 보고

```
## Ship 완료

**브랜치:** {브랜치명}
**커밋:** {hash} {커밋 메시지 1줄}
**변경:** {N}개 파일, +{추가} -{삭제}
**Remote:** origin/{브랜치명}에 푸시 완료

다음 단계:
- PR 생성: /pr
- develop 머지: /merge
```

## 주의사항

- .env, credentials, 시크릿 파일은 커밋에서 **제외**하고 경고
- master 브랜치에서는 직접 커밋하지 않음
- 커밋 메시지는 반드시 **한글**로 작성 (기술 용어 영어 허용)
- 사용자 확인 없이 절대 커밋/푸시하지 않음
