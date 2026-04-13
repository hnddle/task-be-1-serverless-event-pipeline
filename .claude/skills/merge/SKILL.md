---
name: merge
description: Merge current branch into its target following gitflow rules. Features→develop, releases/hotfixes→master+develop.
user-invocable: true
disable-model-invocation: true
allowed-tools: Bash(git *)
---

# Gitflow Merge

## Procedure

### 1. Identify Current Branch
```bash
git branch --show-current
```

### 2. Determine Merge Strategy

**If `feature/*`:**
- Target: `develop`
- Strategy: squash merge
```bash
git checkout develop
git merge --squash feature/{name}
git commit -m "feat: {summarize the feature from squashed commits}"
git branch -d feature/{name}
```

**If `release/*`:**
- Target 1: `master` (merge commit)
- Target 2: `develop` (merge commit)
```bash
git checkout master
git merge --no-ff release/{version} -m "release: merge release/{version} into master"
git tag -a v{version} -m "Release {version}"
git checkout develop
git merge --no-ff release/{version} -m "release: merge release/{version} into develop"
git branch -d release/{version}
```

**If `hotfix/*`:**
- Target 1: `master` (merge commit)
- Target 2: `develop` (merge commit)
```bash
git checkout master
git merge --no-ff hotfix/{name} -m "hotfix: merge hotfix/{name} into master"
git checkout develop
git merge --no-ff hotfix/{name} -m "hotfix: merge hotfix/{name} into develop"
git branch -d hotfix/{name}
```

**If `develop` or `master`:**
- **STOP** — Cannot merge develop or master. Switch to a feature/release/hotfix branch first.

### 3. Report
Display:
```
Merged: {source branch} → {target branch(es)}
Strategy: {squash|merge commit}
Deleted branch: {source branch}
Current branch: {current branch after merge}
```

If there are merge conflicts, stop and inform the user. Do not auto-resolve conflicts.
