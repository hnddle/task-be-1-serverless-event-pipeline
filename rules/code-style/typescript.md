# TypeScript Code Style

- TypeScript strict mode enabled
- Use explicit types for function parameters and return types
- Use `interface` for object shapes, `type` for unions/intersections
- Use `const` by default, `let` only when mutation is needed
- No `any` — use `unknown` and narrow with type guards
- Use optional chaining (`?.`) and nullish coalescing (`??`)
- Async/await over raw promises
- Named exports preferred over default exports
- File naming: kebab-case (`user-service.ts`)
- Component naming: PascalCase (`UserProfile.tsx`)
- Maximum line length: 100 characters
- Linter: ESLint
- Formatter: Prettier
