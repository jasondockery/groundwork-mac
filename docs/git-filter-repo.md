# git-filter-repo for history purges (opt-in)

When a credential or private reference has to leave a repository's history, the procedure is the shared runbook, not this page: [groundwork-core `docs/history-purge.md`](https://github.com/jasondockery/groundwork-core/blob/v0.8.1/docs/history-purge.md). Read it before any rewrite. This page records only the Mac install: what Groundwork installs, when, and how you remove it.

`git-filter-repo` is not a default. A normal bootstrap, `chezmoi apply`, or `update-all` does not install it. Groundwork never runs a history rewrite, a force-push, or a tag change as part of setup.

## Turn it on

Bootstrap does not ask this question. On a Mac, run `groundwork-configure`, choose **git-filter-repo**, answer yes, and confirm the diff. That yes is per machine. The next `chezmoi apply` then:

1. installs `pipx` through the optional Brewfile, which never fails the update; and
2. runs `pipx install git-filter-repo`, which installs into your home directory. It needs no root and no administrator prompt.

Running it again changes nothing once the proof below passes. If `pipx` is not there yet, the script says so and retries on the next apply.

## Prove it

```bash
git filter-repo -h | grep -- --sensitive-data-removal
```

The runbook requires that flag. A build older than 2.47 can exist as a distro or Homebrew package and lacks it, so the help text decides, not the package name. The install script runs this same check and reports a failure without stopping the apply.

## Remove it

1. Run `groundwork-configure`, set **git-filter-repo** to no, and confirm. This stops future installs. It does not uninstall a copy you already have.
2. Run `pipx uninstall git-filter-repo`.
3. Optionally run `brew uninstall pipx` if nothing else of yours uses it.
