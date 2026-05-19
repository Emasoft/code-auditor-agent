#!/usr/bin/env python3
"""Software-type detection — implements TRDD-6857f67f §3.1.c.

DETERMINISTIC. Given the same repo state, returns the same list of
DetectedType objects in the same order. Two runs MUST produce
byte-identical detected-types.json.

Detection strategy per row:
- `primary_globs` — file globs (relative to repo root) that must match.
  Existence is enough; content is not inspected at this stage.
- `primary_content` — pairs of (file_glob, list_of_substring_or_regex).
  At least one substring must appear in at least one matched file for
  the primary to be considered "hit". Regex when the string starts with
  `re:`; substring otherwise. Patterns are checked against the first
  64KB of each matched file (deterministic; large-file friendly).
- `disambiguator_*` — same shape; each match boosts confidence.
- `conflicts_with` — if any of these types already matched, this type
  is suppressed (prevents linux_kernel_module from also matching
  library_c when both have *.c files, etc.).

Base confidence starts at 0.85 if primary matched, +0.04 per
disambiguator (cap 0.98).

The registry below is the source of truth. The `_KNOWN_TYPES` mirror
in `scenario_families.py` is asserted equal at module load.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from . import scenario_families as _sf  # for ALL_TYPES mirror consistency check
from .types import DetectedType

CONTENT_PREVIEW_BYTES = 65536
BASE_CONFIDENCE = 0.85
CONFIDENCE_BOOST = 0.04
MAX_CONFIDENCE = 0.98


@dataclass(frozen=True, slots=True)
class TypeFingerprint:
    """One row of §3.1.c."""

    name: str
    primary_globs: tuple[str, ...] = ()
    primary_content: tuple[tuple[str, tuple[str, ...]], ...] = ()
    disambiguator_globs: tuple[str, ...] = ()
    disambiguator_content: tuple[tuple[str, tuple[str, ...]], ...] = ()
    conflicts_with: tuple[str, ...] = ()
    requires_any_of: tuple[str, ...] = ()


# ---- helpers (deterministic) -----------------------------------------------

# Directories that are never scanned for fingerprints (caches, builds, deps).
_SKIP_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        "node_modules",
        ".pnpm-store",
        "vendor",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".venv",
        "venv",
        "env",
        ".env",
        ".tox",
        "dist",
        "build",
        "target",
        "out",
        "bin",
        "obj",
        ".cache",
        ".idea",
        ".vscode",
        ".gradle",
        ".cargo",
        ".terraform",
        ".pulumi",
        "reports",
        "reports_dev",
        "docs_dev",
        "scripts_dev",
        "tests_dev",
        "samples_dev",
        "examples_dev",
        "downloads_dev",
        "libs_dev",
        "builds_dev",
    }
)


def _iter_files(repo_root: Path, glob: str) -> Iterable[Path]:
    """Yield files matching glob, deterministically, with skip-dirs honoured.

    Globs starting with '**/' walk all dirs; otherwise treated as
    repo-root-relative.
    """
    if glob.startswith("**/"):
        pattern = glob[3:]
        for path in sorted(repo_root.rglob(pattern)):
            if any(part in _SKIP_DIRS for part in path.parts):
                continue
            if path.is_file():
                yield path
    else:
        for path in sorted(repo_root.glob(glob)):
            if any(part in _SKIP_DIRS for part in path.parts):
                continue
            if path.is_file():
                yield path


def _file_contains(path: Path, patterns: Iterable[str]) -> bool:
    """True if any pattern matches anywhere in the first preview of the file.

    Pattern syntax:
        "re:..."  — Python regex, matched with re.search
        "..."     — plain substring
    """
    try:
        data = path.read_bytes()[:CONTENT_PREVIEW_BYTES]
    except OSError:
        return False
    try:
        text = data.decode("utf-8", errors="replace")
    except UnicodeDecodeError:
        return False
    for pat in patterns:
        if pat.startswith("re:"):
            if re.search(pat[3:], text):
                return True
        else:
            if pat in text:
                return True
    return False


def _primary_globs_match(repo_root: Path, globs: tuple[str, ...]) -> tuple[bool, list[str]]:
    if not globs:
        return (True, [])
    evidence: list[str] = []
    for g in globs:
        files = list(_iter_files(repo_root, g))
        if files:
            evidence.append(f"{g} matches {len(files)} file(s); first={files[0].relative_to(repo_root)}")
    return (bool(evidence), evidence)


def _content_match(repo_root: Path, content_specs: tuple[tuple[str, tuple[str, ...]], ...]) -> tuple[bool, list[str]]:
    if not content_specs:
        return (True, [])
    evidence: list[str] = []
    for glob, patterns in content_specs:
        for path in _iter_files(repo_root, glob):
            if _file_contains(path, patterns):
                evidence.append(f"{glob} → {path.relative_to(repo_root)} contains one of {list(patterns)}")
                break
    return (len(evidence) == len(content_specs) if content_specs else True, evidence)


def _disambig_match(repo_root: Path, fp: TypeFingerprint) -> list[str]:
    """Run all disambiguators. Return evidence strings for those that hit."""
    evidence: list[str] = []
    for g in fp.disambiguator_globs:
        for path in _iter_files(repo_root, g):
            evidence.append(f"disambig_glob: {g} → {path.relative_to(repo_root)}")
            break
    for glob, patterns in fp.disambiguator_content:
        for path in _iter_files(repo_root, glob):
            if _file_contains(path, patterns):
                evidence.append(f"disambig_content: {path.relative_to(repo_root)} matches one of {list(patterns)}")
                break
    return evidence


# ---- the §3.1.c registry ---------------------------------------------------
# Each row is one TypeFingerprint. Order doesn't matter for correctness
# (the engine sorts results by confidence DESC, then by name). For
# readability we keep them in the same order as the TRDD §3.1.c table.

FINGERPRINTS: tuple[TypeFingerprint, ...] = (
    # ---- Web services ------------------------------------------------------
    TypeFingerprint(
        name="web_service_python",
        primary_content=(
            (
                "**/pyproject.toml",
                (
                    "fastapi",
                    "flask",
                    "django",
                    "starlette",
                    "sanic",
                    "aiohttp",
                    "bottle",
                ),
            ),
        ),
        disambiguator_content=(
            ("**/*.py", ("@app.route", "@app.get", "@app.post", "Flask(__name__)", "FastAPI(", "urls.py")),
        ),
    ),
    TypeFingerprint(
        name="web_service_node",
        primary_content=(
            (
                "**/package.json",
                (
                    '"express":',
                    '"koa":',
                    '"fastify":',
                    '"hapi":',
                    '"@nestjs/',
                    '"next":',
                    '"hono":',
                    '"elysia":',
                ),
            ),
        ),
        disambiguator_content=(
            ("**/*.ts", ("app.get(", "app.post(", "router.get(", "pages/api/")),
            ("**/*.js", ("app.get(", "app.post(", "router.get(", "pages/api/")),
        ),
    ),
    TypeFingerprint(
        name="web_service_go",
        primary_content=(
            (
                "**/go.mod",
                (
                    "github.com/gin-gonic/gin",
                    "github.com/labstack/echo",
                    "github.com/go-chi/chi",
                    "github.com/gofiber/fiber",
                    "github.com/gorilla/mux",
                ),
            ),
        ),
        disambiguator_content=(("**/*.go", ("http.HandleFunc", "r.GET(", "Mux.HandleFunc")),),
    ),
    TypeFingerprint(
        name="web_service_rust",
        primary_content=(
            (
                "**/Cargo.toml",
                ("actix-web", "axum", "rocket", "warp", "hyper", "poem", "salvo"),
            ),
        ),
        disambiguator_content=(("**/*.rs", ("#[get(", "#[post(", "Router::new(", "HttpServer::new(")),),
    ),
    TypeFingerprint(
        name="web_service_ruby",
        primary_content=(("**/Gemfile", ("rails", "sinatra", "hanami", "roda")),),
        disambiguator_globs=("**/config/routes.rb",),
    ),
    TypeFingerprint(
        name="web_service_php",
        primary_content=(("**/composer.json", ("symfony/", "laravel/", "slim/slim")),),
        disambiguator_content=(("**/*.php", ("Route::get", "#[Route(", "Symfony\\Component\\Routing")),),
    ),
    TypeFingerprint(
        name="web_service_java_kotlin",
        primary_content=(
            ("**/pom.xml", ("spring-boot-starter-web", "spring-webflux", "jersey", "vertx-web")),
            ("**/build.gradle", ("spring-boot-starter-web", "spring-webflux")),
            ("**/build.gradle.kts", ("spring-boot-starter-web", "spring-webflux")),
        ),
        disambiguator_content=(
            ("**/*.java", ("@RestController", "@RequestMapping")),
            ("**/*.kt", ("@RestController", "@RequestMapping")),
        ),
    ),
    TypeFingerprint(
        name="web_service_dotnet",
        primary_content=(("**/*.csproj", ("Microsoft.AspNetCore.",)),),
        disambiguator_content=(("**/*.cs", ("WebApplication.CreateBuilder", "MapGet(", "MapPost(")),),
    ),
    # ---- CLI tools ---------------------------------------------------------
    TypeFingerprint(
        name="cli_python",
        primary_content=(
            ("**/pyproject.toml", ("[project.scripts]",)),
            ("**/setup.py", ("console_scripts",)),
        ),
        disambiguator_content=(("**/*.py", ("argparse", "import click", "import typer")),),
        conflicts_with=("web_service_python",),
    ),
    TypeFingerprint(
        name="cli_node",
        primary_content=(("**/package.json", ('"bin":',)),),
        disambiguator_content=(
            ("**/*.js", ("require('yargs')", "require('commander')", "@oclif/")),
            ("**/*.ts", ("from 'yargs'", "from 'commander'", "@oclif/")),
        ),
        conflicts_with=("web_service_node",),
    ),
    TypeFingerprint(
        name="cli_rust",
        primary_content=(("**/Cargo.toml", ("[[bin]]",)),),
        disambiguator_content=(("**/*.rs", ("use clap", "structopt::")),),
        conflicts_with=("web_service_rust",),
    ),
    TypeFingerprint(
        name="cli_go",
        primary_content=(("**/main.go", ("package main",)),),
        disambiguator_content=(("**/*.go", ("flag.Parse(", "github.com/spf13/cobra", "github.com/urfave/cli")),),
        conflicts_with=("web_service_go",),
    ),
    TypeFingerprint(
        name="cli_csharp",
        primary_content=(("**/*.csproj", ("<OutputType>Exe</OutputType>",)),),
        conflicts_with=("web_service_dotnet",),
    ),
    # ---- Libraries (after CLIs, so cli_* wins when both could match) -------
    TypeFingerprint(
        name="library_python",
        primary_globs=("**/pyproject.toml",),
        disambiguator_content=(("**/__init__.py", ("__all__",)),),
        conflicts_with=(
            "web_service_python",
            "cli_python",
            "ml_training",
            "data_pipeline_airflow",
            "data_pipeline_dbt",
            "data_pipeline_prefect",
            "data_pipeline_dagster",
        ),
    ),
    TypeFingerprint(
        name="library_node",
        primary_content=(("**/package.json", ('"main":', '"exports":')),),
        conflicts_with=("web_service_node", "cli_node"),
    ),
    TypeFingerprint(
        name="library_rust",
        primary_content=(("**/Cargo.toml", ("[lib]",)),),
        conflicts_with=("web_service_rust", "cli_rust", "crypto_library"),
    ),
    TypeFingerprint(
        name="library_c",
        primary_globs=("**/CMakeLists.txt", "**/Makefile"),
        disambiguator_content=(("**/*.c", ("re:^\\s*void\\s+\\w+\\s*\\(", "re:^\\s*int\\s+\\w+\\s*\\(")),),
        conflicts_with=(
            "firmware_arduino",
            "firmware_platformio",
            "firmware_zephyr",
            "firmware_espidf",
            "firmware_stm32",
            "firmware_baremetal",
            "linux_kernel_module",
            "linux_kernel_tree",
            "windows_kernel_driver",
            "bsd_kernel",
            "macos_kernel_ext",
            "os_baremetal",
        ),
    ),
    # ---- Mobile ------------------------------------------------------------
    TypeFingerprint(
        name="mobile_android",
        primary_globs=("**/AndroidManifest.xml",),
        disambiguator_content=(
            ("**/build.gradle", ("applicationId",)),
            ("**/build.gradle.kts", ("applicationId",)),
        ),
    ),
    TypeFingerprint(
        name="mobile_ios",
        primary_globs=("**/*.xcodeproj", "**/*.xcworkspace", "**/Info.plist"),
        disambiguator_content=(
            ("**/*.swift", ("@main", "UIApplicationDelegate", "@UIApplicationMain")),
            ("**/*.m", ("UIApplicationMain",)),
        ),
    ),
    # desktop_flutter MUST come before mobile_flutter so its tighter
    # primary check (flutter: AND a desktop platform string) gets a chance
    # to match — once mobile_flutter matches, desktop_flutter's
    # conflicts_with would skip it for the remainder of the run.
    TypeFingerprint(
        name="desktop_flutter",
        primary_content=(
            ("**/pubspec.yaml", ("flutter:",)),
            (
                "**/pubspec.yaml",
                ("flutter_acrylic", "window_manager", "desktop_window", "windows:", "linux:", "macos:"),
            ),
        ),
        conflicts_with=("mobile_flutter",),
    ),
    TypeFingerprint(
        name="mobile_flutter",
        primary_content=(("**/pubspec.yaml", ("flutter:",)),),
        conflicts_with=("desktop_flutter",),
    ),
    TypeFingerprint(
        name="mobile_reactnative",
        primary_content=(("**/package.json", ('"react-native":',)),),
        disambiguator_globs=("**/app.json",),
    ),
    TypeFingerprint(
        name="mobile_kotlin_multiplatform",
        primary_content=(("**/build.gradle.kts", ("kotlin-multiplatform",)),),
    ),
    # ---- Firmware / embedded ----------------------------------------------
    TypeFingerprint(
        name="firmware_arduino",
        primary_globs=("**/*.ino",),
        disambiguator_content=(("**/*.ino", ("void setup(", "void loop(", "pinMode(")),),
    ),
    TypeFingerprint(
        name="firmware_platformio",
        primary_globs=("**/platformio.ini",),
        # NOTE: deliberately NO conflicts_with — PlatformIO is a build-system
        # layer that hosts arduino/espidf/stm32cube/mbed/baremetal. A project
        # using the arduino framework via PlatformIO is BOTH firmware_arduino
        # AND firmware_platformio; the platformio discoverer dispatches per
        # env to the right per-framework extractor. Excluding it when arduino
        # also matches would silently drop the multi-env entry-point coverage.
    ),
    TypeFingerprint(
        name="firmware_zephyr",
        primary_globs=("**/west.yml", "**/prj.conf"),
        disambiguator_content=(("**/*.c", ("SYS_INIT(", "K_THREAD_DEFINE(", "K_WORK_DEFINE(")),),
    ),
    TypeFingerprint(
        name="firmware_espidf",
        primary_globs=("**/sdkconfig", "**/idf_component.yml"),
        disambiguator_content=(
            ("**/main.c", ("app_main(", "esp_event_handler")),
            ("**/main.cpp", ("app_main(", "esp_event_handler")),
        ),
    ),
    TypeFingerprint(
        name="firmware_stm32",
        primary_globs=("**/STM32*.ld", "**/system_stm32*.c"),
        disambiguator_content=(
            ("**/*.c", ("HAL_", "NVIC_", "__HAL_RCC_")),
            ("**/*.h", ("stm32",)),
        ),
    ),
    TypeFingerprint(
        name="firmware_nordic_sdk",
        primary_content=(("**/*.h", ("nrf_", "NRF_SDK", "nrfx_")),),
        conflicts_with=("firmware_zephyr",),
    ),
    TypeFingerprint(
        name="firmware_baremetal",
        primary_globs=("**/startup_*.s", "**/startup.S", "**/boot.S"),
        primary_content=(("**/*.ld", ("MEMORY", ".text", ".bss")),),
        disambiguator_content=(
            ("**/*.c", ("_start", "Reset_Handler", "void __attribute__((interrupt))")),
            ("**/*.s", ("_start:", "Reset_Handler:")),
        ),
        conflicts_with=(
            "firmware_arduino",
            "firmware_platformio",
            "firmware_zephyr",
            "firmware_espidf",
            "firmware_stm32",
            "linux_kernel_module",
            "linux_kernel_tree",
        ),
    ),
    # ---- RTOS --------------------------------------------------------------
    TypeFingerprint(
        name="rtos_freertos",
        primary_globs=("**/FreeRTOSConfig.h",),
        disambiguator_content=(("**/*.c", ("xTaskCreate(", "vTaskStartScheduler(", "xQueueCreate(")),),
    ),
    TypeFingerprint(
        name="rtos_zephyr",
        primary_content=(("**/prj.conf", ("CONFIG_KERNEL", "CONFIG_THREAD")),),
        # zephyr-based projects also match firmware_zephyr; both are
        # legitimate (Zephyr IS an RTOS), so no conflict.
    ),
    TypeFingerprint(
        name="rtos_threadx",
        primary_content=(
            ("**/*.h", ("tx_api.h", "tx_user.h")),
            ("**/*.c", ("tx_thread_create(", "tx_kernel_enter(")),
        ),
    ),
    TypeFingerprint(
        name="rtos_chibios",
        primary_globs=("**/chconf.h", "**/halconf.h"),
        disambiguator_content=(("**/*.c", ("chThdCreateStatic(", "chSysInit(")),),
    ),
    # ---- Kernel ------------------------------------------------------------
    TypeFingerprint(
        name="linux_kernel_module",
        primary_content=(
            ("**/Kbuild", ("obj-m",)),
            ("**/Makefile", ("obj-m :=", "obj-m +=")),
        ),
        disambiguator_content=(
            ("**/*.c", ("MODULE_LICENSE", "module_init", "module_exit", "EXPORT_SYMBOL", "<linux/module.h>")),
        ),
    ),
    TypeFingerprint(
        name="linux_kernel_tree",
        primary_globs=("MAINTAINERS",),
        primary_content=(("Kconfig", ("source", "config", "menuconfig")),),
        disambiguator_globs=("arch/x86/**", "arch/arm/**", "arch/arm64/**", "kernel/**", "Documentation/**"),
    ),
    TypeFingerprint(
        name="windows_kernel_driver",
        primary_globs=("**/*.inf", "**/*.inx"),
        disambiguator_content=(("**/*.c", ("DriverEntry", "WdfDriverEntry", "IO_STACK_LOCATION")),),
    ),
    TypeFingerprint(
        name="bsd_kernel",
        primary_globs=("**/sys/kern/**/*.c", "**/sys/dev/**/*.c"),
        disambiguator_content=(("**/*.c", ("MOD_LOAD", "DEVMETHOD", "DECLARE_MODULE")),),
    ),
    TypeFingerprint(
        name="macos_kernel_ext",
        primary_globs=("**/*.kext/**/Info.plist",),
        disambiguator_content=(("**/*.cpp", ("IOService", "OSDeclareDefaultStructors")),),
    ),
    TypeFingerprint(
        name="os_baremetal",
        primary_globs=("**/linker.ld", "**/app.ld"),
        disambiguator_content=(("**/*.c", ("_start", "kernel_main", "void __attribute__((noreturn))")),),
        conflicts_with=(
            "firmware_arduino",
            "firmware_platformio",
            "firmware_zephyr",
            "firmware_espidf",
            "firmware_stm32",
            "firmware_baremetal",
            "linux_kernel_module",
            "linux_kernel_tree",
        ),
    ),
    # ---- Hardware design ---------------------------------------------------
    TypeFingerprint(
        name="fpga_verilog",
        primary_globs=("**/*.v", "**/*.sv"),
        disambiguator_globs=("**/*.xdc", "**/*.lpf", "**/*.sdc"),
        disambiguator_content=(
            ("**/*.v", ("module ", "endmodule")),
            ("**/*.sv", ("module ", "endmodule")),
        ),
    ),
    TypeFingerprint(
        name="fpga_vhdl",
        primary_globs=("**/*.vhd", "**/*.vhdl"),
        disambiguator_globs=("**/*.xdc", "**/*.lpf", "**/*.sdc"),
        disambiguator_content=(("**/*.vhd", ("entity ", " is", "architecture ")),),
    ),
    TypeFingerprint(
        name="asic_design",
        primary_globs=("**/*.sdc",),
        disambiguator_globs=("**/*.def", "**/*.lef"),
    ),
    # ---- Driver (userspace) ------------------------------------------------
    TypeFingerprint(
        name="driver_linux_userspace",
        primary_content=(("**/*.c", ("libusb_", "hid_", "spidev_", "ioctl(")),),
        disambiguator_globs=("**/udev/rules.d/**",),
        conflicts_with=("linux_kernel_module", "linux_kernel_tree"),
    ),
    # ---- Browser extensions ------------------------------------------------
    TypeFingerprint(
        name="browser_ext_chrome",
        primary_content=(("**/manifest.json", ('"manifest_version": 3', "background", "content_scripts")),),
        disambiguator_content=(("**/*.js", ("chrome.runtime", "chrome.tabs", "chrome.storage")),),
    ),
    TypeFingerprint(
        name="browser_ext_firefox",
        primary_content=(("**/manifest.json", ("browser_specific_settings", "gecko")),),
        disambiguator_content=(("**/*.js", ("browser.runtime", "browser.tabs")),),
    ),
    TypeFingerprint(
        name="browser_ext_safari",
        primary_globs=("**/*.safariextz",),
    ),
    # ---- Games -------------------------------------------------------------
    TypeFingerprint(
        name="game_unity",
        primary_globs=("**/ProjectSettings/*.asset", "**/Assets/**/*.cs"),
        disambiguator_content=(("**/*.cs", ("MonoBehaviour", "UnityEngine")),),
    ),
    TypeFingerprint(
        name="game_unreal",
        primary_globs=("**/*.uproject",),
        disambiguator_content=(("**/*.h", ("AActor", "UCLASS(", "GENERATED_BODY")),),
    ),
    TypeFingerprint(
        name="game_godot",
        primary_globs=("**/project.godot", "**/*.tscn", "**/*.gd"),
    ),
    TypeFingerprint(
        name="game_engine",
        primary_content=(
            ("**/*.cpp", ("class Renderer", "SceneGraph", "ShaderCompiler")),
            ("**/*.h", ("class Renderer", "SceneGraph", "ShaderCompiler")),
        ),
        conflicts_with=("game_unity", "game_unreal", "game_godot"),
    ),
    # ---- Compiler / parser ------------------------------------------------
    TypeFingerprint(
        name="compiler_parser",
        primary_globs=("**/*.lex", "**/*.y", "**/*.tree-sitter", "**/*.pest", "**/*.g4"),
        disambiguator_content=(
            ("**/*.py", ("re:def\\s+parse_\\w+", "re:def\\s+tokenize_\\w+")),
            ("**/*.rs", ("re:fn\\s+parse_\\w+", "re:fn\\s+tokenize_\\w+")),
            ("**/*.c", ("re:\\w+_parse\\s*\\(", "re:\\w+_tokenize\\s*\\(")),
        ),
    ),
    # ---- IaC --------------------------------------------------------------
    TypeFingerprint(
        name="iac_terraform",
        primary_globs=("**/*.tf",),
        disambiguator_globs=("**/terraform.tfvars",),
    ),
    TypeFingerprint(
        name="iac_pulumi",
        primary_globs=("**/Pulumi.yaml",),
    ),
    TypeFingerprint(
        name="iac_helm",
        primary_globs=("**/Chart.yaml",),
        disambiguator_globs=("**/templates/**",),
    ),
    TypeFingerprint(
        name="iac_ansible",
        primary_globs=("**/playbook.yml", "**/playbook.yaml"),
        disambiguator_globs=("**/roles/**", "**/tasks/**"),
    ),
    TypeFingerprint(
        name="iac_cloudformation",
        primary_content=(
            ("**/*.template", ("AWSTemplateFormatVersion",)),
            ("**/*.yaml", ("AWSTemplateFormatVersion",)),
            ("**/*.yml", ("AWSTemplateFormatVersion",)),
        ),
    ),
    TypeFingerprint(
        name="iac_kustomize",
        primary_globs=("**/kustomization.yaml",),
    ),
    TypeFingerprint(
        name="iac_docker_compose",
        primary_globs=("**/docker-compose.yml", "**/compose.yaml", "**/compose.yml"),
    ),
    TypeFingerprint(
        name="iac_k8s_operator",
        primary_globs=("**/kubebuilder.yaml",),
        disambiguator_content=(("**/*.go", ("Reconcile(", "controllerutil.")),),
    ),
    # ---- Data pipelines ---------------------------------------------------
    TypeFingerprint(
        name="data_pipeline_airflow",
        primary_globs=("**/airflow.cfg",),
        disambiguator_content=(("**/*.py", ("from airflow", "DAG(", "@dag", "@task")),),
    ),
    TypeFingerprint(
        name="data_pipeline_dbt",
        primary_globs=("**/dbt_project.yml",),
        disambiguator_globs=("**/models/**",),
    ),
    TypeFingerprint(
        name="data_pipeline_prefect",
        primary_globs=("**/prefect.yaml",),
        disambiguator_content=(("**/*.py", ("@flow", "@task", "from prefect")),),
    ),
    TypeFingerprint(
        name="data_pipeline_dagster",
        primary_globs=("**/dagster.yaml",),
        disambiguator_content=(("**/*.py", ("@asset", "@op", "from dagster")),),
    ),
    # ---- ML training ------------------------------------------------------
    TypeFingerprint(
        name="ml_training",
        primary_content=(
            ("**/pyproject.toml", ("torch", "tensorflow", "jax", "transformers", "scikit-learn", "lightning")),
            ("**/requirements.txt", ("torch", "tensorflow", "jax", "transformers", "scikit-learn", "lightning")),
        ),
        disambiguator_content=(("**/*.py", ("nn.Module", "train_step", "optimizer.step", "loss.backward")),),
        conflicts_with=("web_service_python", "library_python"),
    ),
    # ---- Crypto -----------------------------------------------------------
    TypeFingerprint(
        name="crypto_library",
        primary_content=(
            ("**/Cargo.toml", ("aes", "rsa", "ed25519", "hkdf", "x25519")),
            ("**/go.mod", ("crypto/aes", "crypto/rsa", "crypto/ed25519")),
        ),
        disambiguator_content=(
            ("**/*.rs", ("constant_time", "subtle::")),
            ("**/*.go", ("subtle.ConstantTimeCompare",)),
        ),
    ),
    # ---- Network protocol ------------------------------------------------
    TypeFingerprint(
        name="network_protocol_impl",
        primary_content=(
            ("**/*.c", ("parse_packet", "encode_packet", "packet_header")),
            ("**/*.rs", ("parse_packet", "PacketHeader")),
            ("**/*.go", ("parsePacket", "PacketHeader")),
        ),
    ),
    # ---- Database ---------------------------------------------------------
    TypeFingerprint(
        name="database_engine",
        primary_content=(
            ("**/*.c", ("wal_append", "page_alloc", "commit_record", "btree_split")),
            ("**/*.rs", ("wal_append", "page_alloc", "commit_record", "btree_split")),
        ),
    ),
    # ---- Distributed ------------------------------------------------------
    TypeFingerprint(
        name="distributed_system",
        primary_content=(
            ("**/*.go", ("appendEntries", "requestVote", "proposeValue")),
            ("**/*.rs", ("appendEntries", "request_vote", "propose_value")),
            ("**/*.java", ("appendEntries", "requestVote")),
        ),
    ),
    # ---- Desktop ----------------------------------------------------------
    TypeFingerprint(
        name="desktop_qt",
        primary_content=(
            ("**/CMakeLists.txt", ("find_package(Qt6", "find_package(Qt5")),
            ("**/*.pro", ("QT +=", "QT +=")),
        ),
        disambiguator_content=(("**/*.cpp", ("QApplication", "QMainWindow")),),
    ),
    TypeFingerprint(
        name="desktop_gtk",
        primary_content=(
            ("**/Cargo.toml", ("gtk4", "gtk3")),
            ("**/CMakeLists.txt", ("gtk4", "gtk-3.0")),
        ),
        disambiguator_content=(
            ("**/*.c", ("gtk_init", "gtk_application_new")),
            ("**/*.rs", ("gtk::Application::new",)),
        ),
    ),
    TypeFingerprint(
        name="desktop_electron",
        primary_content=(("**/package.json", ('"electron":',)),),
        disambiguator_content=(
            ("**/*.js", ("BrowserWindow", "app.on('ready'")),
            ("**/*.ts", ("BrowserWindow", "app.on('ready'")),
        ),
    ),
    TypeFingerprint(
        name="desktop_tauri",
        primary_globs=("**/tauri.conf.json", "**/src-tauri/**"),
        disambiguator_content=(("**/*.rs", ("#[tauri::command]",)),),
    ),
    TypeFingerprint(
        name="webgl_three",
        primary_content=(("**/package.json", ('"three":', '"@react-three/fiber":')),),
        disambiguator_content=(
            ("**/*.ts", ("WebGLRenderer", "Scene(")),
            ("**/*.js", ("WebGLRenderer", "new Scene(")),
        ),
    ),
    # ---- Websocket / MQ ---------------------------------------------------
    TypeFingerprint(
        name="websocket_server",
        primary_content=(
            ("**/package.json", ('"ws":', '"socket.io":')),
            ("**/Cargo.toml", ("tokio-tungstenite",)),
            ("**/go.mod", ("github.com/gorilla/websocket",)),
        ),
        disambiguator_content=(
            ("**/*.js", ("onmessage", "WebSocket(")),
            ("**/*.ts", ("onmessage", "WebSocket(")),
        ),
    ),
    TypeFingerprint(
        name="message_queue_consumer",
        primary_content=(
            ("**/pyproject.toml", ("kafka-python", "confluent-kafka", "pika", "redis", "boto3", "nats-py")),
            ("**/package.json", ('"kafkajs":', '"amqplib":', '"redis":', '"@aws-sdk/client-sqs":', '"nats":')),
            ("**/go.mod", ("github.com/segmentio/kafka-go", "github.com/streadway/amqp", "github.com/nats-io/nats.go")),
        ),
        disambiguator_content=(
            ("**/*.py", ("consume(", "subscribe(", "channel.basic_consume")),
            ("**/*.js", ("consume(", "subscribe(", "ack()")),
        ),
    ),
)


# ---- detection driver ------------------------------------------------------


def detect_all(repo_root: Path) -> tuple[DetectedType, ...]:
    """Return all DetectedType results for the repo, deterministic order.

    Order: confidence DESC, then name ASC.
    """
    repo_root = repo_root.resolve()
    matched: dict[str, DetectedType] = {}
    matched_names: set[str] = set()

    for fp in FINGERPRINTS:
        # Run conflicts check first — if any of conflicts_with already matched, skip.
        if any(c in matched_names for c in fp.conflicts_with):
            continue

        primary_glob_ok, glob_ev = _primary_globs_match(repo_root, fp.primary_globs)
        primary_content_ok, content_ev = _content_match(repo_root, fp.primary_content)
        # Either kind of primary check (if both empty, both are "True" by default)
        # is acceptable; both must be satisfied if both provided.
        if not (primary_glob_ok and primary_content_ok):
            continue
        if not fp.primary_globs and not fp.primary_content:
            # A fingerprint with no primary checks is a misconfiguration —
            # skip rather than match everything.
            continue

        disambig_ev = _disambig_match(repo_root, fp)
        confidence = min(MAX_CONFIDENCE, BASE_CONFIDENCE + CONFIDENCE_BOOST * len(disambig_ev))

        evidence_list = glob_ev + content_ev + disambig_ev
        matched[fp.name] = DetectedType(
            type=fp.name,
            confidence=confidence,
            evidence=tuple(evidence_list[:8]),  # cap evidence to keep output bounded
        )
        matched_names.add(fp.name)

    if not matched:
        return (
            DetectedType(
                type="unknown_software",
                confidence=BASE_CONFIDENCE,
                evidence=("no fingerprint matched; falling back to unknown_software discoverer",),
            ),
        )

    # Sort: confidence DESC, then name ASC.
    return tuple(sorted(matched.values(), key=lambda d: (-d.confidence, d.type)))


# Public mirror — asserted equal to scenario_families._KNOWN_TYPES at import time.
ALL_TYPES: frozenset[str] = frozenset(fp.name for fp in FINGERPRINTS) | {"unknown_software"}


# Self-check: mirror in scenario_families.py must be in sync with FINGERPRINTS.
# Import-time assertion to catch drift early.
def _assert_mirror_consistent() -> None:
    diff_a = ALL_TYPES - _sf._KNOWN_TYPES
    diff_b = _sf._KNOWN_TYPES - ALL_TYPES
    if diff_a or diff_b:
        raise RuntimeError(
            "detect_software_type.ALL_TYPES disagrees with scenario_families._KNOWN_TYPES.\n"
            f"  only in detect_software_type: {sorted(diff_a)}\n"
            f"  only in scenario_families:   {sorted(diff_b)}"
        )


_assert_mirror_consistent()


if __name__ == "__main__":
    import json
    import sys

    if len(sys.argv) != 2:
        sys.exit("Usage: detect_software_type.py <repo_root>")
    result = detect_all(Path(sys.argv[1]))
    print(json.dumps([dt.to_json() for dt in result], indent=2))
