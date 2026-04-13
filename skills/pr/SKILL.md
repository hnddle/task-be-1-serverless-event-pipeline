---
name: pr
description: 현재 브랜치의 변경 내역을 분석하여 GitHub PR을 자동 생성. Usage /pr 또는 /pr "추가 설명"
argument-hint: (선택) PR 설명에 포함할 추가 컨텍스트
user-invocable: true
disable-model-invocation: true
allowed-tools: Read, Glob, Grep, Bash(git *), Bash(gh *)
---

# /pr — GitHub Pull Request 자동 생성

현재 브랜치의 커밋 내역을 분석하여 적절한 PR title/description을 생성하고 `gh pr create`로 PR을 생성한다.

## 사전 조건

- `gh` CLI 설치 및 인증 완료 (`gh auth status`로 확인)
- 현재 브랜치가 remote에 push된 상태

## 실행 절차

### 1. 상태 확인

```bash
gh auth status
git branch --show-current
git status -sb
```

default 브랜치를 확인한다:
```bash
gh repo view --json defaultBranchRef -q '.defaultBranchRef.name'
```

push되지 않은 커밋이 있으면 먼저 push한다:
```bash
git push -u origin $(git branch --show-current)
```

### 2. 변경 내역 분석

```bash
# DEFAULT_BRANCH는 1단계에서 확인한 값 사용
git log origin/{DEFAULT_BRANCH}..HEAD --pretty=format:"%h %s"
git diff origin/{DEFAULT_BRANCH}..HEAD --stat
```

모든 커밋을 분석하여 PR의 전체 맥락을 파악한다.

### 3. Base 브랜치 결정

Gitflow 규칙에 따라:

| 현재 브랜치 | Base 브랜치 |
|-------------|-------------|
| `feature/*` | `develop` (있으면) 또는 default 브랜치 |
| `release/*` | default 브랜치 |
| `hotfix/*` | default 브랜치 |

```bash
git branch -a | grep -q develop && echo "develop exists" || echo "no develop"
```

### 4. PR Title 생성

**규칙:**
- 70자 이내
- Conventional Commits type 접두사 사용
- **한글**로 작성 (기술 용어 영어 허용)
- 커밋이 단일이면 커밋 메시지를 그대로 사용
- 커밋이 복수이면 전체 변경을 요약

### 5. PR Description 생성

**형식:**
```markdown
## Summary
- {주요 변경 사항 1~3줄 bullet}

## 주요 변경 내역
| 커밋 | 설명 |
|------|------|
| `{hash}` | {커밋 메시지} |

## Test plan
- [ ] {테스트 항목}

🤖 Generated with [Claude Code](https://claude.com/claude-code)
```

**규칙:**
- Summary는 1~3개 bullet point로 핵심만
- 모든 커밋을 테이블에 포함
- Test plan은 변경 내용에 맞는 구체적 항목
- 사용자가 $ARGUMENTS로 추가 컨텍스트를 제공한 경우 Summary에 반영

### 6. 사용자 확인

```
## /pr 요약

**Base:** {base 브랜치} ← **Head:** {현재 브랜치}
**Title:** {PR 제목}

**Description:**
{PR 본문 미리보기}

진행할까요?
```

### 7. PR 생성

```bash
gh pr create --base {base_branch} --title "{title}" --body "$(cat <<'EOF'
{description}
EOF
)"
```

### 8. 결과 보고

```
## PR 생성 완료

**PR:** {PR URL}
**Base:** {base} ← **Head:** {head}
**Title:** {title}

다음 단계:
- 리뷰어 지정: GitHub에서 설정
- 머지: /merge
```

## 주의사항

- `gh` CLI 미설치 시 설치 안내 (`winget install GitHub.cli` 또는 `brew install gh`)
- 미인증 시 `gh auth login` 안내
- push되지 않은 변경이 있으면 먼저 push
- 이미 동일 브랜치의 PR이 열려있으면 경고 후 중단
- 사용자 확인 없이 절대 PR을 생성하지 않음
