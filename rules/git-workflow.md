# Git Workflow — Gitflow Strategy

## Branch Structure
- `master` — 프로덕션 코드. 직접 커밋 금지.
- `develop` — 통합 브랜치. 모든 feature가 먼저 여기로 merge됨.
- `feature/*` — 새 기능. `develop`에서 분기.
- `release/*` — 릴리스 준비. `develop`에서 분기.
- `hotfix/*` — 긴급 수정. `master`에서 분기.

## Branch Naming
- Feature: `feature/step-{X}-{Y}-{short-description}` (예: `feature/step-1-1-project-setup`)
- Release: `release/{version}` (예: `release/0.1.0`)
- Hotfix: `hotfix/{short-description}` (예: `hotfix/fix-db-connection`)

## Commit Message Format
```
<type>(<scope>): <한글 subject>
```

Types:
- `feat:` — 새로운 기능 추가
- `fix:` — 버그 수정
- `docs:` — 문서 변경
- `style:` — 포매팅 변경 (코드 변경 없음)
- `refactor:` — 기능 변경 없는 코드 구조 개선
- `perf:` — 성능 개선
- `test:` — 테스트만 변경
- `chore:` — 빌드, 설정 등 기타 변경
- `ci:` — CI 설정 변경

예시:
```
feat(step1): 브랜드명 자동 생성 기능 추가
fix(auth): 비회원 세션 만료 후 데이터 유실 수정
chore: Docker Compose 개발 환경 설정 추가
```

## Merge Rules
- Feature → develop (squash merge 권장)
- Release → master AND develop (merge commit, `--no-ff`)
- Hotfix → master AND develop (merge commit, `--no-ff`)
- master 또는 develop에 force-push 금지
