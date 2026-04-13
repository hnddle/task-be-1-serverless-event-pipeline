---
name: branch
description: Create and manage gitflow branches. Usage /branch feature|release|hotfix [name]
argument-hint: (type) (name) — e.g., "feature auth-module" or "release 0.1.0" or "hotfix db-fix"
user-invocable: true
disable-model-invocation: true
allowed-tools: Bash(git *)
---

# Gitflow Branch Management

## Input
Branch type and name: $ARGUMENTS

$0 = branch type (feature, release, hotfix, develop, init)
$1 = branch name or version

## Commands

### `feature [name]`
```bash
git checkout develop
git pull origin develop 2>/dev/null || true
git checkout -b feature/$1
```

### `release [version]`
```bash
git checkout develop
git pull origin develop 2>/dev/null || true
git checkout -b release/$1
```

### `hotfix [name]`
```bash
git checkout master
git pull origin master 2>/dev/null || true
git checkout -b hotfix/$1
```

### `develop`
Switch to develop branch:
```bash
git checkout develop
```

### `init`
Initialize gitflow branches (first-time setup):
```bash
# Ensure we're on master
git checkout master 2>/dev/null || git checkout -b master
# Create develop from master
git checkout -b develop 2>/dev/null || git checkout develop
```

## After Creating Branch
Display:
```
Created branch: {type}/{name}
Based on: {parent branch}
Current branch: {result of git branch --show-current}
```
