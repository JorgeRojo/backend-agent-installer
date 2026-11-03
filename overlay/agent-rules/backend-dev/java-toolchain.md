# Java Toolchain and Language Server

backend-agent-installer sets up the Java toolchain for shells that load no rc file, which is what
every agent shell is. It takes precedence over the Linux branch of `windows-mount-toolchain`.

## Building

- For a repo under `/home/...`, run `mvn` directly. On PATH it is `~/.local/bin/mvn`: sdkman's
  Maven 3.9.16 with `JAVA_HOME` forced to Temurin 17, the JDK the repos build with.
- Never download Maven or a JDK to `/tmp`, and never pass `MVN_HOME` to `run_mvn.sh` for a
  `/home` repo: that Maven runs on whatever `java` it finds, which is the wrong JDK.
- Bare `java` on PATH is the system OpenJDK 21 early-access build. Never use it to judge the
  project JDK; `mvn -v` reports the one Maven compiles with.
- If `mvn -v` does not print Maven 3.9.16 and Java 17, stop and report it. The fix is
  `~/projects/backend-agent-installer/install.sh --check`, not a workaround in the session.
- Repos under `/mnt/<drive>/...` still use the Windows toolchain from `windows-mount-toolchain`.

## Navigating Java code

A Java language server (Eclipse JDT LS) backs the `code` tool in kiro-cli and the `LSP` tool in
Claude Code. Use it for definitions, references, implementations and diagnostics of Java
symbols: it resolves overloads, inheritance and Lombok-generated members, which text search
cannot.

- The first request in a repo can time out while the server imports the Maven project (about
  3 minutes cold for rpc-core, under 40 seconds once cached). Retry; do not fall back to grep
  on the first timeout.
- The server holds about 1.8 GB while indexing a large reactor. Do not open several repos in
  one session to run a single lookup.
