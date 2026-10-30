# syntax=docker/dockerfile:1.28@sha256:bb22d9815c728170f72750f4e5b0d672e06176142e1d602c7e66c050100b7e5b
FROM ubuntu:24.04@sha256:68ee22004a9109b44973313b02ff7b1de250f1de0f5ecb628d73f579aaff33ac

ENV DEBIAN_FRONTEND=noninteractive
ENV LANG=en_US.UTF-8
ENV LC_ALL=en_US.UTF-8

RUN apt-get update && apt-get install -y --no-install-recommends \
    zsh git curl wget ca-certificates locales sudo unzip tar gzip xz-utils gnupg \
    tmux neovim ripgrep fd-find bat fzf jq shellcheck build-essential \
  && ln -sf "$(command -v fdfind)" /usr/local/bin/fd \
  && ln -sf "$(command -v batcat)" /usr/local/bin/bat \
  && locale-gen en_US.UTF-8 \
  && rm -rf /var/lib/apt/lists/*

COPY docker/install-headless-tools.sh /tmp/install-headless-tools.sh
RUN --mount=type=secret,id=github_token bash /tmp/install-headless-tools.sh && rm /tmp/install-headless-tools.sh

ARG USER=dev
ARG USER_UID=1000
ARG USER_GID=$USER_UID
RUN set -eux; \
  if getent group "$USER_GID" >/dev/null; then \
    existing_group="$(getent group "$USER_GID" | cut -d: -f1)"; \
    if [ "$existing_group" != "$USER" ]; then groupmod -n "$USER" "$existing_group"; fi; \
  else \
    groupadd --gid "$USER_GID" "$USER"; \
  fi; \
  if getent passwd "$USER_UID" >/dev/null; then \
    existing_user="$(getent passwd "$USER_UID" | cut -d: -f1)"; \
    if [ "$existing_user" != "$USER" ]; then userdel -r "$existing_user" 2>/dev/null || userdel "$existing_user"; fi; \
  fi; \
  useradd --uid "$USER_UID" --gid "$USER_GID" -m -s /usr/bin/zsh "$USER"; \
  echo "$USER ALL=(ALL) NOPASSWD:ALL" > "/etc/sudoers.d/$USER"; \
  chmod 0440 "/etc/sudoers.d/$USER"

USER $USER
WORKDIR /home/$USER
RUN mkdir -p /home/$USER/.config/chezmoi
# Keep repository runtime shims before package-manager binaries for direct commands.
ENV PATH=/home/$USER/.local/bin:/home/$USER/.cargo/bin:/home/$USER/.local/share/mise/shims:/home/linuxbrew/.linuxbrew/bin:/home/linuxbrew/.linuxbrew/sbin:$PATH

RUN sh -c "$(curl -fsSL https://get.chezmoi.io)" -- -b /home/$USER/.local/bin
# Homebrew install plus `brew bundle` is nearly all of the ~300s `chezmoi apply`
# below, and apply reruns whenever anything under home/ changes. Install the
# packages in their own layer keyed only on the Brewfile and the templates it
# includes, so an unrelated home/ edit reuses the cached (already compressed)
# package layer and only the small config layer is rebuilt and exported.
# chezmoi apply stays the authority: it still runs the same run_before and
# run_onchange hooks and finds the packages installed. A bundle failure here is
# deliberately not fatal for that reason.
COPY docker/chezmoi.headless.toml /tmp/chezmoi.headless.toml
COPY home/.chezmoitemplates /opt/groundwork/home/.chezmoitemplates
COPY home/dot_config/homebrew /opt/groundwork/home/dot_config/homebrew
RUN <<'PREWARM'
set -eux
sudo apt-get update
sudo apt-get install -y --no-install-recommends build-essential procps curl file git
sudo rm -rf /var/lib/apt/lists/*
NONINTERACTIVE=1 /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
eval "$(/home/linuxbrew/.linuxbrew/bin/brew shellenv)"
chezmoi --config /tmp/chezmoi.headless.toml --source /opt/groundwork/home execute-template \
  < /opt/groundwork/home/dot_config/homebrew/Brewfile.tmpl >/tmp/Brewfile
export HOMEBREW_NO_ASK=1 HOMEBREW_NO_ANALYTICS=1 HOMEBREW_CURL_RETRIES=3 HOMEBREW_CASK_OPTS=--require-sha
for attempt in 1 2 3; do
  if brew bundle install --no-upgrade --file=/tmp/Brewfile; then break; fi
  echo "prewarm brew bundle attempt $attempt failed; chezmoi apply will finish any remainder" >&2
done
rm -f /tmp/Brewfile
sudo rm -f /tmp/chezmoi.headless.toml
PREWARM
# chezmoi --source /opt/groundwork reads .chezmoiroot and then home/. Copy only
# that source. A docs, script, or workflow change must not rebuild the apply
# layer: on main's 2026-10-28 docker-build (run 40700178469) `COPY .` missed
# the cache and `chezmoi apply` took 267s, then exporting the new layer took
# 175s. The install-headless-tools layer above was already cached.
COPY --chown=$USER:$USER .chezmoiroot /opt/groundwork/.chezmoiroot
COPY --chown=$USER:$USER .chezmoiversion /opt/groundwork/.chezmoiversion
COPY --chown=$USER:$USER home /opt/groundwork/home
COPY --chown=$USER:$USER docker/chezmoi.headless.toml /home/$USER/.config/chezmoi/chezmoi.toml
RUN chezmoi --source /opt/groundwork apply
# The smoke entrypoint is not chezmoi source. Copy it after apply so a script
# edit does not rebuild the apply layer.
COPY --chown=$USER:$USER scripts/smoke-docker-image /opt/groundwork/scripts/smoke-docker-image
COPY --chown=$USER:$USER scripts/test-developer-tool-visibility /opt/groundwork/scripts/test-developer-tool-visibility
COPY --chown=$USER:$USER scripts/.developer-tool-surface-test.zsh /opt/groundwork/scripts/.developer-tool-surface-test.zsh

CMD ["zsh"]
