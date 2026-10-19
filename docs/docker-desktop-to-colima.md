# Move from Docker Desktop to Colima on macOS

Groundwork recommends Colima with the Docker CLI on personal and managed Macs. It gives developers and coding agents the same inspectable container workflow on both. Docker Desktop remains an explicit alternative when its integrations are required. This guide is the single migration procedure for the Groundwork family. Native Linux, Omarchy, and WSL use their own container runtime; Apple hardware running Linux does not need a macOS VM manager.

Installing the new default does not transfer existing workloads. A Docker **context** selects an engine; each engine has its own containers, images, named volumes, and build cache. Keep Docker Desktop available until you have verified the replacement. Device policy takes precedence on managed Macs.

## Choose the work your situation needs

| Existing setup | Required work |
| --- | --- |
| No data or containers to keep | Install Colima, start it, and verify the selected context. |
| Disposable Compose projects | Pull or rebuild images and recreate services from the project’s Compose files. |
| Source code in bind mounts | Keep the host files; check that Colima can mount their paths with the expected permissions. |
| Databases or named volumes | Stop writes, take consistent backups, restore into new volumes, and verify the data. Prefer the database’s own dump/restore tools. |
| Images that cannot be rebuilt | Export from the old engine with `docker image save`; import with `docker image load`. |
| Dev Containers, Testcontainers, custom sockets or networking | Verify each integration against Colima, including socket paths, published ports, DNS, private registries, and CPU architecture. |
| Kubernetes or Desktop extensions | Recreate cluster resources and persistent data separately; choose equivalents for required Desktop integrations before switching. |

A container image backup excludes attached volume contents. Build caches are usually disposable. Docker Desktop’s VM disk is a recovery copy for Desktop, not a Colima disk image. See [Docker’s backup guidance](https://docs.docker.com/desktop/settings-and-maintenance/backup-and-restore/) and [volume backup and restoration](https://docs.docker.com/engine/storage/volumes/#back-up-restore-or-migrate-data-volumes).

## 1. Inventory and back up before switching

Run these read-only commands against the engine you use today:

```bash
docker context ls
docker context show
docker ps --all
docker compose ls
docker image ls
docker volume ls
docker buildx ls
```

Record the Desktop context name from that output. The examples below use a shell variable; set it to your observed name, which is often `desktop-linux`:

```bash
desktop_context=desktop-linux
```

Review project Compose files, environment files, secrets, bind mounts, named volumes, registry access, and any changes made only inside a container. Keep backups private. For a database, stop application writes and use its documented backup procedure. Verify a restore before deleting the original data. To retain an image that you cannot rebuild:

```bash
mkdir -p "$HOME/Backups/docker-migration"
chmod 700 "$HOME/Backups/docker-migration"
docker --context "$desktop_context" image save -o "$HOME/Backups/docker-migration/my-image.tar" my-image:tag
```

Replace the example image with your own. Do not use `docker compose down --volumes`, volume pruning, or a factory reset during migration. They delete data you may still need.

## 2. Install and start the common Mac runtime

In `groundwork-configure`, select **Container backend → Colima + Docker CLI**, review the preview, and apply. Groundwork installs Colima, Docker CLI, Compose, Buildx, and the macOS credential helper. It adds the Homebrew CLI plugin directory to Docker’s existing configuration while preserving other settings. Existing Docker Desktop data stays in place.

For a Mac not yet using the updated Groundwork source, the equivalent package installation is:

```bash
brew update
brew install colima docker docker-compose docker-buildx docker-credential-helper
```

Follow the formula caveats to add Homebrew’s plugin directory to `cliPluginsExtraDirs` in `~/.docker/config.json` if `docker compose version` or `docker buildx version` cannot find its plugin. Preserve existing entries. Do not replace the whole Docker configuration.

After backups are complete, quit Docker Desktop to avoid competing workloads or published ports, then run:

```bash
colima start
docker context ls
docker context use colima
docker info
docker compose version
docker buildx version
```

`colima start` normally selects its context automatically. Review existing `DOCKER_HOST` and `DOCKER_CONTEXT` environment overrides if the CLI reaches the wrong engine. Prefer explicit contexts while moving data. Colima’s default socket is `~/.colima/default/docker.sock`; confirm it with `colima status`. Configure tools that require a socket through their supported settings instead of replacing `/var/run/docker.sock` globally. [Colima’s context and socket guidance](https://colima.run/docs/faq/#docker)

Groundwork’s Colima template affects new instances. Use `colima start --edit` for an existing instance; deleting an instance to pick up configuration would delete its container data.

## 3. Restore and verify one project at a time

Pull or rebuild reproducible images. For a saved image:

```bash
docker --context colima image load -i "$HOME/Backups/docker-migration/my-image.tar"
```

Restore database dumps or volume backups into the new engine, then recreate the project with its reviewed Compose configuration. For a project that uses Compose:

```bash
docker --context colima compose up --detach --build
docker --context colima compose ps
```

Check application behavior, record counts or other data checks, logs, health checks, bind-mount writes, ports, private-registry pulls, Dev Containers/Testcontainers, and any amd64-only images on Apple Silicon. Keep the old services stopped so two copies do not write to the same external system. Verify a normal stop/start and a reboot before treating the move as complete.

For rollback before removal, stop the Colima project, reopen Docker Desktop, and select the recorded Desktop context. Data written after switching is now in Colima; decide how to transfer it back before resuming writes on Desktop.

## 4. Optionally uninstall Docker Desktop after acceptance

Uninstall only after the replacement works, persistent data is verified, and recovery backups are retained. Docker’s uninstaller can destroy Desktop’s containers, images, and volumes. Groundwork never runs this removal automatically.

First ensure the Groundwork container setting is Colima so a later apply will not reinstall Desktop. Check package ownership:

```bash
brew list --cask
```

If Homebrew lists `docker-desktop`, quit Docker Desktop and remove that exact cask:

```bash
brew uninstall --cask docker-desktop
```

For an older installed token, use the exact token reported by Homebrew. For a manually installed app, use Docker Desktop’s **Troubleshoot → Uninstall**, or its official uninstaller:

```bash
/Applications/Docker.app/Contents/MacOS/uninstall
```

After the vendor uninstaller finishes, move a remaining Docker application bundle to Trash. Do not run both removal paths blindly. [Docker’s macOS uninstall instructions](https://docs.docker.com/desktop/uninstall/)

**Keep `~/.docker`.** Colima and the Docker CLI share its contexts, plugins, and registry configuration. The vendor’s generic cleanup instructions include removing this directory; that is inappropriate when continuing to use Docker through Colima. Review Desktop-specific leftovers individually after backup instead of applying blanket cleanup or `--zap`.

If `~/.docker/config.json` still selects `credsStore: "desktop"`, use the installed `osxkeychain` helper through Docker’s supported credential-store setting and sign back in to the required registries with `docker login`. Preserve unrelated `credHelpers` entries and do not publish this file or credentials. If Desktop removal broke command links, repair the independently managed tools:

```bash
brew reinstall docker docker-compose docker-buildx docker-credential-helper
hash -r
docker context use colima
docker info
docker compose version
docker buildx version
```

Repeat the project checks. Retain backups until you are satisfied that everything required has moved. Removing Desktop is separate from deleting old backups.
