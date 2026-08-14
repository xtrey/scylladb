# Local SonarQube server (Docker) for the ScyllaDB SonarQube POC

`sonarqube.sh` spins up a local [SonarQube Community] server in Docker with the
[sonar-cxx] plugin installed, so you can analyze ScyllaDB C++ sources and import
the coverage / static-analysis reports produced by the `scripts/sonar-*.sh`
pipeline.

[SonarQube Community]: https://hub.docker.com/_/sonarqube
[sonar-cxx]: https://github.com/SonarOpenCommunity/sonar-cxx

## Layout

```
docker/sonarqube/
├── sonarqube.sh            # lifecycle: up / wait / provision / status / logs / restart / down / destroy
├── config/
│   ├── sonar.properties    # server config, bind-mounted -> /opt/sonarqube/conf/sonar.properties
│   └── disabled-rules.txt  # C++ rule keys to switch OFF (applied by `provision`)
└── plugins/                # plugin jars, bind-mounted -> /opt/sonarqube/extensions/plugins/
                            # (sonar-cxx is auto-downloaded here; drop extra jars in too)
```

## Quick start

```bash
cd docker/sonarqube

./sonarqube.sh up          # pull image, download sonar-cxx, start the server
./sonarqube.sh wait        # block until http://localhost:9000 is UP
./sonarqube.sh provision   # set admin password + disable rules from config/disabled-rules.txt
```

Then browse to <http://localhost:9000> (login `admin`, password from
`SONAR_ADMIN_PASSWORD`, default `scylla-sonar-admin`).

Stop it with `./sonarqube.sh down` (keeps the analysis data) or wipe everything
with `./sonarqube.sh destroy`.

> **Elasticsearch requirement:** SonarQube bundles Elasticsearch, which needs
> `vm.max_map_count >= 524288`. `up` tries to raise it automatically (via `sudo
> sysctl`); if it can't, run `sudo sysctl -w vm.max_map_count=524288` yourself
> first and add it to `/etc/sysctl.conf` to persist.

## Injecting configuration / switching checks off

There are three independent injection points, all file-driven — no UI clicking,
nothing baked into an image:

1. **Server behaviour — `config/sonar.properties`.** Bind-mounted into the
   container's `conf/`. Edit it (ports, DB, JVM memory, telemetry) and
   `./sonarqube.sh restart` to apply.

2. **C++ rules (native sonar-cxx checks) — `config/disabled-rules.txt`.** List
   the rule keys you want turned off, one per line, then run
   `./sonarqube.sh provision`. It copies the built-in C++ profile to an editable
   `scylla-cxx` profile, makes it the default, and deactivates each listed rule.
   Re-running `provision` re-applies the file.

3. **Imported external issues (clang-tidy / cppcheck) — at scan time.** These
   come from the reports referenced in `sonar-project.properties`
   (`sonar.cxx.clangtidy.reportPaths`, `sonar.cxx.cppcheck.reportPaths`). To drop
   them from a run, override the paths on the scanner command line, e.g.
   `-Dsonar.cxx.clangtidy.reportPaths= -Dsonar.cxx.cppcheck.reportPaths=`. Which
   clang-tidy checks run at all is controlled by `CHECKS` in
   `scripts/sonar-cxx-analyze.sh`.

Additional plugins: drop any `*.jar` into `plugins/` and `./sonarqube.sh
restart`.

## End-to-end with the coverage / analysis pipeline

The reports the scanner imports are produced from a `coverage`-mode build
(see `../../scripts/`):

```bash
# 1. build coverage mode and run the suites you want covered
./configure.py --mode coverage
ninja build/coverage/scylla            # + the unit-test binaries you need
./test.py --mode coverage --coverage   # produces *.profraw + testlog/coverage

# 2. turn raw profiles into a Cobertura report (memory-safe, resumable)
scripts/sonar-coverage.sh              # -> build/coverage/sonar/coverage.cobertura.xml

# 3. (optional) whole-repo clang-tidy / cppcheck reports
scripts/sonar-cxx-analyze.sh           # -> build/coverage/sonar/{clang-tidy.txt,cppcheck.xml}

# 4. start + provision the server (this directory)
docker/sonarqube/sonarqube.sh up && docker/sonarqube/sonarqube.sh provision

# 5. run the scanner against the repo (mounts the checkout at /usr/src)
docker run --rm --network=host \
  -e SONAR_HOST_URL="http://localhost:9000" \
  -e SONAR_TOKEN="<token from the UI: My Account -> Security>" \
  -v "$PWD:/usr/src" sonarsource/sonar-scanner-cli
```

`sonar-project.properties` (repo root) already declares the C++ file suffixes,
exclusions, and the report paths above.

## Configuration knobs (env vars)

| Var | Default | Purpose |
|-----|---------|---------|
| `SONAR_PORT` | `9000` | Host port for the web UI. |
| `SONAR_IMAGE` | `sonarqube:community` | SonarQube image/tag. Pin e.g. `sonarqube:2025.4-community` for reproducibility. |
| `SONAR_CXX_TAG` / `SONAR_CXX_JAR` | `cxx-2.3.0` / `sonar-cxx-plugin-2.3.0.1496.jar` | sonar-cxx release to install. |
| `SONAR_CXX_URL` | GitHub release URL | Override to install from a mirror/local file server. |
| `SONAR_ADMIN_PASSWORD` | `scylla-sonar-admin` | Admin password set by `provision`. |
| `SONAR_CONTAINER` | `scylla-sonarqube` | Container name. |
| `SONAR_DATA_VOL` / `SONAR_LOGS_VOL` | `scylla_sonarqube_data` / `_logs` | Named volumes for persistence. |
| `SONAR_WAIT_TIMEOUT` | `300` | Seconds `wait`/`provision` will poll for `UP`. |

## Version notes

sonar-cxx `2.3.0` requires **Java 21** on both server and scanner side and is
tested against SonarQube Community Build 25.8 (Server 2025.4 LTA) and 26.1
(Server 2026.1 LTA). The default `sonarqube:community` image tracks a compatible
build; pin `SONAR_IMAGE` if you need an exact version.
