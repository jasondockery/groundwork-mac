# Local inference on Apple Silicon

Shared evaluation, licensing, provenance, hardware fit, privacy, and removal judgment live in groundwork-core's [local model guide](https://github.com/jasondockery/groundwork-core/blob/main/docs/local-models.md) (added in [groundwork-core#19](https://github.com/jasondockery/groundwork-core/pull/19)). This page does not repeat that guide. It records only the Mac runtime: what Groundwork installs, on which machines, and how you start, stop, update, and remove it.

Local inference stays off until you turn it on. A normal bootstrap, `chezmoi apply`, or `update-all` does not install this runtime, does not start it, and does not download model weights.

## What Groundwork installs

The managed runtime is the Homebrew formula `ollama` from homebrew-core. Reviewed on 2026-10-25, that formula's stable version was 0.40.11 ([formula](https://github.com/Homebrew/homebrew-core/blob/master/Formula/o/ollama.rb), [Ollama](https://ollama.com/)).

On Apple Silicon the formula builds with the MLX engine (`-tags=mlx`) and depends on `mlx-c`. The same build uses Homebrew's `darwin` CMake preset, which is the Metal llama.cpp path for GGUF models. Ollama's own docs say the MLX engine is enabled by default on macOS arm64, and that Apple GPUs use Metal ([development](https://docs.ollama.com/development), [hardware support](https://docs.ollama.com/gpu)). A model tag whose name ends in `-mlx` uses the MLX engine. A tag without that suffix still uses the GPU through Metal when `ollama ps` reports GPU, but it is not the MLX engine.

This fits Groundwork's package lifecycle better than the other two common Apple Silicon tools, which stay available for you to install yourself:

- `mlx-lm` is Apple's Python package ([mlx-lm](https://github.com/ml-explore/mlx-lm)). On 2026-10-25, PyPI release 0.32.2 required Python 3.11 or newer. MLX itself requires a native Apple Silicon Python and macOS 14 or newer ([install](https://ml-explore.github.io/mlx/build/html/install.html)). `uv` is already installed, so `uv tool install mlx-lm` is the isolated install, and `uv tool upgrade mlx-lm` updates it. Groundwork does not install it. The default `mlx_lm.generate` and `mlx_lm.chat` commands select `mlx-community/Llama-3.2-3B-Instruct-4bit` when you omit `--model`, and that downloads weights. Pass `--model` only after you have read that model's card, license, and size.
- LM Studio's Homebrew cask token is `lm-studio` ([cask](https://github.com/Homebrew/homebrew-cask/blob/master/Casks/l/lm-studio.rb)). On 2026-10-25 the cask version was 0.4.26,4. The vendor requires Apple Silicon and macOS 14 or newer ([system requirements](https://lmstudio.ai/docs/app/system-requirements)). The cask's own floor is macOS Monterey, which is looser than the vendor, and the cask sets `auto_updates true`, so the app updates outside `update-all`. Groundwork does not install it. `brew install --cask lm-studio` is the manual desktop install. The app does not download a model until you choose one.

Revisit this choice when the formula stops shipping the MLX build on Apple Silicon, when the bottled macOS range changes, or when you need a workflow only mlx-lm or LM Studio provides.

## Supported machines

Groundwork installs the formula only when all of these are true:

- `local_inference` is the boolean `true`
- the machine is macOS (`darwin`)
- the architecture is Apple Silicon (`arm64`)

That includes a headless Apple Silicon Mac. The formula is a command-line program. Intel Macs, Linux, and WSL keep a stored `true` and do not install it. `groundwork-profile` prints `inactive (stored enabled; Apple Silicon only)` in that case.

Ollama's macOS app documentation requires macOS Sonoma 14 or newer, with CPU and GPU support on Apple Silicon and CPU only on Intel ([macOS](https://docs.ollama.com/macos)). Intel is outside this path.

Homebrew bottles for formula 0.40.11 exist for these Apple Silicon releases:

| Bottle | macOS |
| --- | --- |
| `arm64_sequoia` | macOS 15 Sequoia |
| `arm64_tahoe` | macOS 26 Tahoe |
| `arm64_golden_gate` | macOS 27 Golden Gate |

The formula publishes no Intel macOS bottle. Its Linux bottles are CPU-only, and this flag does not install them. Sonoma 14 meets Ollama's stated floor and MLX's macOS 14 floor, but this formula has no Sonoma bottle. A source build there is not the supported path. The formula lives in `Brewfile.optional`, so a failed install is reported and the rest of the update still succeeds.

Homebrew's formula test on Apple Silicon checks that `ollama --help` loads `libmlxc.dylib`. Groundwork's tests do not run that check and do not download a model. After you load a model yourself, `ollama ps` shows the processor. `100% GPU` means the model was placed on the GPU. `100% CPU` means it was not.

## Turn it on

Bootstrap does not ask this question. On an existing machine, run `groundwork-configure`, choose **Local inference**, answer yes, and confirm the diff. The next apply installs the formula through the optional Brewfile. `update-all` later upgrades the formula with your other Homebrew packages. Neither step pulls a model or starts a server.

If `ollama-app` is already installed, the formula install stops until you remove the app. Both provide the `ollama` command. The optional installer prints this when it sees the cask:

```bash
brew uninstall --cask ollama-app
```

That leaves models in `~/.ollama`. Do not add `--zap` unless you mean to delete those models too. The cask's zap list includes `~/.ollama`.

Optional personal apps can still install the menu-bar cask `ollama-app` when local inference is off. That app is a different install: it can start its own server and it updates itself (`auto_updates true`). Turning local inference on removes the cask from the desired Brewfile. It does not uninstall an app that is already there.

## Choose a model before you download it

Read the shared guide first. Then, before any download:

1. Open the model's page on the [Ollama library](https://ollama.com/library). Record the publisher, exact tag, license, and the size printed on that page.
2. For the MLX engine, choose a tag whose name ends in `-mlx`. Confirm on the library page that the tag exists. Groundwork does not name a permanent default model.
3. Skip a `:cloud` tag when inference must stay on this Mac. Those tags send the prompt to Ollama's hosted service and need an ollama.com account. `ollama signin` is that account. Groundwork never runs it.
4. Compare the published size with free disk and with unified memory. Leave room for macOS and for the context the runtime keeps beside the file. The shared guide explains why file size is not the whole memory cost.
5. Download only when that page is acceptable:

```bash
ollama pull NAME
```

`ollama show NAME` prints the license and parameters of the copy you downloaded. `ollama ls` lists local models and their disk use. Keep model files out of Git repositories. They live under `~/.ollama/models` ([Ollama FAQ](https://docs.ollama.com/faq)).

## Run and stop

Groundwork does not write an Ollama configuration file and does not set environment variables for it. `ollama serve` is the run path that keeps Ollama's own defaults:

```bash
ollama serve
```

Stop that process with Ctrl+C. That stops the server and does not delete models. The default listen address is loopback port 11434. Groundwork does not set `OLLAMA_HOST`. Changing that variable to a non-loopback address exposes the server; do that only as a separate decision.

Unload one model without stopping the server:

```bash
ollama stop NAME
```

Homebrew also defines a background service. Groundwork does not start it. If you start it yourself with `brew services start ollama`, you are accepting Homebrew's service settings, not Groundwork's. In formula 0.40.11 those settings differ from a plain `ollama serve`:

| Variable | Homebrew service value | Why it is listed |
| --- | --- | --- |
| `OLLAMA_FLASH_ATTENTION` | `1` | Set only in the formula's `brew services` block. Groundwork does not set it. |
| `OLLAMA_KV_CACHE_TYPE` | `q8_0` | Set only in the formula's `brew services` block. Groundwork does not set it. A quantized cache uses less memory and can change output. |

Stop that service with `brew services stop ollama`. `ollama serve --help` on the installed version lists the variables Ollama itself documents.

## Agents and cloud sign-in

Enabling local inference does not change Claude, Codex, ChatGPT, T3 Code, OpenCode, or any other cloud sign-in. Groundwork does not write a base URL, an API key, or a fallback from a hosted model to a local one. Pointing a tool at `http://127.0.0.1:11434` is a separate choice inside that tool. Ollama's `ollama launch` can wire an integration; Groundwork does not run it. Leave a local-to-hosted fallback off unless you explicitly choose it and the shared guide's data boundary allows it.

## Update and removal

`update-all` upgrades the installed formula. It does not pull models and it does not refresh weights you already downloaded. To move to a different model, repeat the library-page check and `ollama pull` the new tag, then `ollama rm` the tag you no longer want.

To remove the runtime:

1. Run `groundwork-configure`, set **Local inference** to no, and confirm. The next apply drops `brew "ollama"` from the optional Brewfile.
2. Run `brew uninstall ollama`. That removes the formula and leaves `~/.ollama` in place.
3. To delete downloaded weights, logs, and Ollama's local config, run `rm -rf ~/.ollama`. That is permanent. Groundwork never runs it for you.

`uv tool uninstall mlx-lm` removes a copy you installed yourself. `brew uninstall --cask lm-studio` removes a copy of LM Studio you installed yourself. Add `--zap` only when you also want that app's own support files removed, and read the cask's zap list first.
