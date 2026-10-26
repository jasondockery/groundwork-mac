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

In `groundwork-configure`, select **Container backend → Colima + Docker CLI**, review the preview, and apply. Groundwork installs Colima, Docker CLI, Compose, Buildx, and the macOS credential helper. Its Docker config modify script adds the Homebrew CLI plugin directory only when that directory is missing, and sets `credsStore` to `osxkeychain` only when the key is absent. Existing `auths`, an existing `credsStore` (including `desktop`), `currentContext`, and every other key stay. When those two requirements are already satisfied, the file bytes are left unchanged, so a routine Docker Desktop or Colima rewrite does not make `update-all` prompt. Existing Docker Desktop data stays in place.

For a Mac not yet using the updated Groundwork source, the equivalent package installation is:

```bash
brew update
brew install colima docker docker-compose docker-buildx docker-credential-helper
```

Follow the formula caveats to add Homebrew’s plugin directory to `cliPluginsExtraDirs` in `~/.docker/config.json` if `docker compose version` or `docker buildx version` cannot find its plugin. Preserve existing entries, including `auths` and `credsStore`. Do not replace the whole Docker configuration. Groundwork’s modify script follows that same rule: it merges only the plugin directory and a missing `credsStore`, and it does not rewrite the file when those keys are already present.

After backups are complete, quit Docker Desktop to avoid competing workloads or published ports, then run:

```bash
groundwork-colima-start
docker context ls
docker context use colima
docker info
docker compose version
docker buildx version
```

`colima start` normally selects its context automatically. Review existing `DOCKER_HOST` and `DOCKER_CONTEXT` environment overrides if the CLI reaches the wrong engine. Prefer explicit contexts while moving data. Colima’s default socket is `~/.colima/default/docker.sock`; confirm it with `colima status`. Configure tools that require a socket through their supported settings instead of replacing `/var/run/docker.sock` globally. [Colima’s context and socket guidance](https://colima.run/docs/faq/#docker)

Groundwork’s Colima template affects new instances. It writes `rosetta: true` only when Rosetta is already installed at apply time. When Rosetta is absent, that key is omitted, so a new instance does not warn that Rosetta is missing. An existing instance can still have the key. Install Rosetta if you want it, run `chezmoi apply`, then run `colima start --edit` and set `rosetta: true` on that instance. Colima still warns when `oahd` is not running. Deleting an instance to pick up configuration deletes its container data.

When `COLIMA_HOME` is unset and `~/.colima` is already a directory, Groundwork’s own `colima` commands set `COLIMA_HOME` to that directory so Colima does not warn that it is ignoring `XDG_CONFIG_HOME`. A `COLIMA_HOME` you already set is left unchanged for `start --help`, `start`, and `stop`. Groundwork does not move or delete `~/.colima`. It also does not install Rosetta when Colima warns that Rosetta is missing; that warning is expected for an arm64-only install.

## New instance disk size

Use `groundwork-colima-start` when creating a new Colima profile. Groundwork checks free space on the filesystem that will hold the data disk: `LIMA_HOME` when set, or the Colima home `_lima` directory otherwise. It chooses about half the currently available space, rounds down to whole GiB, and caps the limit at 100 GiB. When 20 to under 40 GiB is free, the 20 GiB floor takes precedence over half-free sizing and can exceed half of the measured free space. Below 20 GiB free, the command stops before creating the instance. Colima stores the data disk sparsely and it grows as used, so the configured limit can still consume host capacity and the filesystem can still fill. The command prints the measured storage path, current free space, chosen limit, and reason.

This is a disk size limit, not a reservation or a guarantee that the host volume cannot run out later. Other files can use the remaining space while Colima's data disk grows.

The sizing applies only to a profile with no saved Colima config or data disk. Existing profiles start without an automatic disk-size change. To grow an existing instance, stop it, open its configuration, increase `disk` to a larger GiB value, save, then start it again. Colima can grow this disk but cannot shrink it:

```bash
colima stop
colima start --edit
# Increase the disk value, save the configuration, and let Colima start.
```

Direct `colima start` remains available for custom Colima options; it uses the saved template and does not calculate a size from current free space.

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

If `~/.docker/config.json` still selects `credsStore: "desktop"`, use the installed `osxkeychain` helper through Docker’s supported credential-store setting and sign back in to the required registries with `docker login`. Groundwork will not replace a `credsStore` you or Docker already wrote. Preserve unrelated `credHelpers` entries and `auths`, and do not publish this file or credentials. If Desktop removal broke command links, repair the independently managed tools:

```bash
brew reinstall docker docker-compose docker-buildx docker-credential-helper
hash -r
docker context use colima
docker info
docker compose version
docker buildx version
```

Repeat the project checks. Retain backups until you are satisfied that everything required has moved. Removing Desktop is separate from deleting old backups.

## 5. Recover a Colima instance that has no data disk

Groundwork's Colima template pins `disk: 100`, which is Colima's normal default. Colima reads that template as the whole configuration for a new instance, so a template that omits `disk:` stores `disk: 0` and creates a 0-byte data disk. `colima start` then never finishes.

`groundwork-doctor` and the `update-all` Colima start step read the same home and profile Colima 0.10.3 would use. They use `COLIMA_HOME` only when that directory exists. Otherwise they use `~/.colima` when it exists, and otherwise `$XDG_CONFIG_HOME/colima` when that variable is set. If it is unset, macOS uses `~/.colima` and other systems use `$HOME/.config/colima`. `COLIMA_PROFILE` selects the instance. An empty value, `default`, and `colima` are the default instance. Any other value is kept as the `--profile` argument, and one leading `colima-` is removed only when choosing that instance's config directory and disk name. So `colima-default` is a different instance from `default`, and `work` and `colima-work` are the same instance. `LIMA_HOME`, when set, replaces the `_lima` directory that holds the data disk. They look for `disk: 0` in that profile's `colima.yaml`, or a 0-byte datadisk for that profile. They print a recovery command that names the home, profile, and Lima directory they actually read, and they skip the start. They never delete the instance.

The printed command deletes that instance's containers, images, and data disk. Run it only after you accept that loss. `colima delete --force` removes the instance and leaves the Lima data disk in place, including the 0-byte disk from a start that never finished and a lock that can still name that instance. The command then runs `limactl disk delete --force`, which removes the disk even when that lock remains. It starts a new instance through `groundwork-colima-start`, which chooses a sparse disk limit from current free space, with a 20 GiB floor and a 100 GiB cap. If the Lima filesystem has less than 20 GiB free, the helper stops without starting the new instance. Lima ignores a disk that is already gone, so that step continues. Any other disk-delete failure stops the command before `groundwork-colima-start`. `$profile` is the original `COLIMA_PROFILE` value, or `default` when that value is empty, `default`, or `colima`. `$profile_id` is `colima` for that default instance. Otherwise it is `colima-` plus the profile name with one leading `colima-` removed. `$lima_home` is the `_lima` directory that was read:

```bash
LIMA_HOME="$lima_home" COLIMA_HOME="$colima_home" colima --profile="$profile" delete --force && LIMA_HOME="$lima_home" limactl disk delete --force "$profile_id" && LIMA_HOME="$lima_home" COLIMA_HOME="$colima_home" groundwork-colima-start --profile="$profile"
```

Groundwork does not install Rosetta. The template writes `rosetta: true` only when Rosetta is already installed at apply time. Otherwise the key is omitted and a new instance does not warn that Rosetta is missing. An instance created earlier can still have the key. Install Rosetta if you want it, run `chezmoi apply`, then run `colima start --edit` and set `rosetta: true` on that existing instance. Colima still warns when `oahd` is not running. Do not delete the instance just to change this setting.
