Development Principles: The Twelve-Factor App
This project strictly adheres to The Twelve-Factor App methodology for building scalable, maintainable, and cloud-native applications. All code generation and architectural decisions must reflect these principles.

I. Codebase
Principle: One codebase tracked in revision control, many deploys.

Action: Maintain a single repository for all environments (Dev, Staging, Prod). Do not create environment-specific code branches.

II. Dependencies
Principle: Explicitly declare and isolate dependencies.

Action: - Python: Use requirements.txt or poetry.

TypeScript/Node.js: Use package.json.

Never rely on the implicit existence of system-wide packages.

III. Config
Principle: Store config in the environment.

Action: - Strictly separate config (DB credentials, API keys) from code.

Use environment variables (process.env or os.environ).

Use .env files for local development only; never commit them to Git.

IV. Backing Services
Principle: Treat backing services as attached resources.

Action: Treat databases, caches, and message brokers as attached resources via URL/credentials. They must be swappable without changing code.

V. Build, Release, Run
Principle: Strictly separate build and run stages.

Action: - Build: Transform code into an executable bundle.

Release: Combine build with config.

Run: Execute the release in the execution environment.

Never change code at runtime.

VI. Processes
Principle: Execute the app as one or more stateless processes.

Action: - Processes must be stateless and share nothing.

Persistent data must be stored in a stateful backing service (DB, Redis).

VII. Port Binding
Principle: Export services via port binding.

Action: The app must be self-contained and bind to a port to serve requests (e.g., via an embedded server). It should not rely on an external web server injector.

VIII. Concurrency
Principle: Scale out via the process model.

Action: Design the app to scale horizontally by adding more independent processes rather than making a single process larger (Scale out, not Scale up).

IX. Disposability
Principle: Maximize robustness with fast startup and graceful shutdown.

Action: - Minimize startup time.

Handle SIGTERM gracefully: finish current tasks, refuse new ones, and exit cleanly.

X. Dev/Prod Parity
Principle: Keep development, staging, and production as similar as possible.

Action: Use the same backing services (e.g., Postgres instead of SQLite) in local development to minimize "it works on my machine" bugs.

XI. Logs
Principle: Treat logs as event streams.

Action: Do not manage log files within the app. Stream logs to stdout. Let the execution environment (Azure Monitor, CloudWatch) handle capture and storage.

XII. Admin Processes
Principle: Run admin/management tasks as one-off processes.

Action: Run database migrations or one-time scripts against a release using the same environment and codebase as the app's long-running processes.