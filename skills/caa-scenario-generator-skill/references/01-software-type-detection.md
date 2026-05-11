# Software type detection registry

## Table of Contents

- [Overview](#overview)
- [Detection algorithm](#detection-algorithm)
- [Registry by category](#the-registry-by-category)
- [Conflict resolution](#conflict-resolution)

## Overview

Implements TRDD-6857f67f §3.1.c. The detector is fully data-driven via
`scripts/scenario_generator/detect_software_type.py`. Each row is one
`TypeFingerprint` dataclass with these fields:

- `primary_globs` — globs (relative to repo root) that MUST match for the
  primary check to fire. Existence is enough.
- `primary_content` — pairs `(file_glob, list_of_patterns)`. At least one
  pattern must appear in at least one matched file. Patterns starting with
  `re:` are regex; otherwise plain substring. Patterns are checked against
  the first 64 KB of each matched file.
- `disambiguator_*` — same shape; each match boosts confidence (+0.04 per
  hit, cap 0.98).
- `conflicts_with` — if any of these types already matched, this type is
  suppressed. Used to prevent (for example) `library_c` from also matching
  `linux_kernel_module` because both contain `*.c` files.

Base confidence starts at **0.85** if primary matched. Two runs on the same
repo produce byte-identical output (`detected-types.json`).

## Detection algorithm

```
for fp in FINGERPRINTS:               # source-ordered iteration
    if any(c in matched for c in fp.conflicts_with):
        skip
    if not primary_globs_match(fp) or not primary_content_match(fp):
        skip
    confidence = 0.85 + 0.04 * len(disambiguator_hits)
    record(fp.name, confidence, evidence)
return sorted(matches, key=(-confidence, name))
```

The order of `FINGERPRINTS` does not affect correctness (final output is
sorted), but it does affect `conflicts_with` semantics — a fingerprint can
suppress a LATER one but not a previously-recorded one. Web frameworks come
first, then CLIs, then libraries (the most generic), then mobile, firmware,
RTOS, kernel, hardware-description, drivers, browser-extensions, games,
compiler/parser, IaC, data pipelines, ML, crypto, network protocols,
databases, distributed systems, desktop, WebGL, websocket/MQ.

## The registry by category

Each subsection below names the types in that category. The full row data
(globs, content patterns, disambiguators, conflicts) is in
`scripts/scenario_generator/detect_software_type.py` (one `TypeFingerprint`
per row). See the source for ground truth; this document mirrors the
high-level shape.

### Web services

| Type | Primary signal |
|---|---|
| `web_service_python` | pyproject/requirements lists fastapi/flask/django/starlette/sanic/aiohttp/bottle |
| `web_service_node` | package.json lists express/koa/fastify/hapi/nestjs/next/hono/elysia |
| `web_service_go` | go.mod requires gin/echo/chi/fiber/gorilla-mux |
| `web_service_rust` | Cargo.toml lists actix-web/axum/rocket/warp/hyper/poem/salvo |
| `web_service_ruby` | Gemfile lists rails/sinatra/hanami/roda |
| `web_service_php` | composer.json lists symfony/laravel/slim |
| `web_service_java_kotlin` | pom.xml/build.gradle lists spring-boot/spring-webflux/jersey/vertx-web |
| `web_service_dotnet` | *.csproj references Microsoft.AspNetCore.* |

### CLI tools

| Type | Primary signal |
|---|---|
| `cli_python` | pyproject `[project.scripts]` OR setup.py `console_scripts` |
| `cli_node` | package.json `bin:` field |
| `cli_rust` | Cargo.toml `[[bin]]` section |
| `cli_go` | `main.go` with `package main` |
| `cli_csharp` | *.csproj `<OutputType>Exe</OutputType>` |

### Libraries

| Type | Primary signal |
|---|---|
| `library_python` | pyproject without scripts/web frameworks; `__all__` in __init__.py |
| `library_node` | package.json with `main:`/`exports:` and no `bin:` |
| `library_rust` | Cargo.toml `[lib]` only, no `[[bin]]` |
| `library_c` | CMakeLists.txt or Makefile; `*.c` files |

### Mobile

| Type | Primary signal |
|---|---|
| `mobile_android` | `AndroidManifest.xml` |
| `mobile_ios` | `*.xcodeproj`/`*.xcworkspace` + `Info.plist` |
| `mobile_flutter` | `pubspec.yaml` with `flutter:` |
| `mobile_reactnative` | package.json lists `react-native` + `app.json` |
| `mobile_kotlin_multiplatform` | `build.gradle.kts` applies `kotlin-multiplatform` |

### Firmware / embedded

| Type | Primary signal |
|---|---|
| `firmware_arduino` | `*.ino` files; `setup()` + `loop()` |
| `firmware_platformio` | `platformio.ini` |
| `firmware_zephyr` | `west.yml` + `prj.conf` |
| `firmware_espidf` | `sdkconfig` + `idf_component.yml` |
| `firmware_stm32` | `STM32*.ld` + `system_stm32*.c` |
| `firmware_nordic_sdk` | `nrf_`/`NRF_SDK` headers |
| `firmware_baremetal` | linker script + `startup_*.s` + `_start` |

### RTOS

| Type | Primary signal |
|---|---|
| `rtos_freertos` | `FreeRTOSConfig.h` |
| `rtos_zephyr` | `prj.conf` with CONFIG_KERNEL (also matches firmware_zephyr — both legitimate) |
| `rtos_threadx` | `<tx_api.h>` includes |
| `rtos_chibios` | `chconf.h`/`halconf.h` |

### Kernel / OS

| Type | Primary signal |
|---|---|
| `linux_kernel_module` | Kbuild/Makefile with `obj-m` + `MODULE_LICENSE` |
| `linux_kernel_tree` | `MAINTAINERS` + `Kconfig` at root + `arch/<arch>/` |
| `windows_kernel_driver` | `*.inf`/`*.inx` + `DriverEntry`/`WdfDriverEntry` |
| `bsd_kernel` | `sys/kern/` + `sys/dev/` |
| `macos_kernel_ext` | `*.kext`/`Info.plist` + IOService |
| `os_baremetal` | Linker script + `kernel_main`/`_start` |

### Hardware design

| Type | Primary signal |
|---|---|
| `fpga_verilog` | `*.v`/`*.sv` + `*.xdc`/`*.lpf`/`*.sdc` |
| `fpga_vhdl` | `*.vhd`/`*.vhdl` + constraint files |
| `asic_design` | `*.sdc` + DEF/LEF files |

### Drivers (userspace)

| Type | Primary signal |
|---|---|
| `driver_linux_userspace` | libusb/hidapi/spidev + udev rules |

### Browser extensions

| Type | Primary signal |
|---|---|
| `browser_ext_chrome` | manifest.json with `manifest_version: 3` + chrome.runtime |
| `browser_ext_firefox` | manifest.json with `browser_specific_settings.gecko` |
| `browser_ext_safari` | `*.safariextz` |

### Games

| Type | Primary signal |
|---|---|
| `game_unity` | `Assets/` + `ProjectSettings/` + MonoBehaviour |
| `game_unreal` | `*.uproject` + UCLASS macros |
| `game_godot` | `project.godot` + `*.tscn`/`*.gd` |
| `game_engine` | rendering/scene-graph/shader-compiler patterns (non-game-engine code) |

### Compiler / parser

| Type | Primary signal |
|---|---|
| `compiler_parser` | `*.lex`/`*.y`/`*.tree-sitter`/`*.pest`/`*.g4` |

### IaC

| Type | Primary signal |
|---|---|
| `iac_terraform` | `*.tf` + `terraform.tfvars` |
| `iac_pulumi` | `Pulumi.yaml` |
| `iac_helm` | `Chart.yaml` + `templates/` |
| `iac_ansible` | `playbook.yml` + `roles/` |
| `iac_cloudformation` | `AWSTemplateFormatVersion` |
| `iac_kustomize` | `kustomization.yaml` |
| `iac_docker_compose` | `docker-compose.yml`/`compose.yaml` |
| `iac_k8s_operator` | `kubebuilder.yaml` + Reconcile method |

### Data pipelines / ML / crypto

| Type | Primary signal |
|---|---|
| `data_pipeline_airflow` | `airflow.cfg` + `DAG(...)`/`@dag` |
| `data_pipeline_dbt` | `dbt_project.yml` + `models/` |
| `data_pipeline_prefect` | `prefect.yaml` + `@flow` |
| `data_pipeline_dagster` | `dagster.yaml` + `@asset` |
| `ml_training` | torch/tensorflow/jax/transformers/sklearn + nn.Module/train_step |
| `crypto_library` | aes/rsa/ed25519/hkdf/x25519 deps + constant-time helpers |

### Network / database / distributed

| Type | Primary signal |
|---|---|
| `network_protocol_impl` | `parse_packet`/`encode_packet`/packet_header structs |
| `database_engine` | `wal_append`/`page_alloc`/`commit_record`/`btree_split` |
| `distributed_system` | `appendEntries`/`requestVote`/`proposeValue` (Raft/Paxos/CRDT) |

### Desktop

| Type | Primary signal |
|---|---|
| `desktop_qt` | CMakeLists Qt6/Qt5 + QApplication/QMainWindow |
| `desktop_gtk` | gtk4/gtk3 deps + gtk_init/Application::new |
| `desktop_electron` | package.json lists electron + BrowserWindow |
| `desktop_tauri` | `tauri.conf.json` + `#[tauri::command]` |
| `desktop_flutter` | `pubspec.yaml` + desktop targets enabled |
| `webgl_three` | package.json lists three / @react-three/fiber |

### Websocket / message queue

| Type | Primary signal |
|---|---|
| `websocket_server` | ws/socket.io/tokio-tungstenite/gorilla-websocket |
| `message_queue_consumer` | kafka/rabbitmq/redis/sqs/nats client libs |

### Fallback

| Type | Primary signal |
|---|---|
| `unknown_software` | none of the above match |

## Conflict resolution

Some fingerprints overlap. The `conflicts_with` field on each suppresses
later matches:

- `cli_python` suppresses `library_python` (a project with
  `[project.scripts]` is a CLI, not a library).
- `web_service_python` suppresses `cli_python` (FastAPI service that has
  a script entry is still primarily a web service).
- `library_c` suppresses `firmware_*`, `linux_kernel_*`,
  `windows_kernel_driver`, `bsd_kernel`, `macos_kernel_ext`,
  `os_baremetal` (those are special-purpose; library_c is for generic
  C/C++ libs).
- `os_baremetal` suppresses `firmware_*` and `linux_kernel_*` (the
  baremetal OS pattern overrides firmware-style + module-style guesses
  when the linker script + `_start` is present).
- `desktop_flutter` suppresses `mobile_flutter` when desktop targets are
  enabled.

These are conservative — false-negatives (a real type missing) are
preferred over false-positives (a wrong type firing). The discoverer
catalog (03) and the family registry (04) are organised so any false
negative falls back to `unknown_software`, which never silently fails.
