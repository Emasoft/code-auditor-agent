// Fixture exercising the two clap idioms the discoverer must handle:
//   1. Derive-macro Subcommand enum with variants (with and without
//      explicit name + about overrides, plus a `///` doc comment).
//   2. Builder-API `Command::new("...")` plus chained subcommands.
use clap::{Parser, Subcommand, Command};

#[derive(Parser)]
#[command(name = "fixture-cli", version)]
struct Cli {
    #[command(subcommand)]
    cmd: Action,
}

#[derive(Subcommand)]
enum Action {
    /// Print a friendly greeting to the named user.
    Greet { name: String },

    #[command(name = "say-goodbye", about = "Wave goodbye before exiting.")]
    Goodbye { user: Option<String>, loud: bool },

    /// Copy files from <src> to <dst>.
    Sync { src: String, dst: String },
}

fn builder_main() {
    // Builder-form chain — each Command::new is one CLI surface.
    let _app = Command::new("fixture-cli-builder")
        .about("Fixture using the builder API")
        .subcommand(
            Command::new("status")
                .about("Print current status to stdout."),
        )
        .subcommand(Command::new("reset"));
}

fn main() {
    let _cli = Cli::parse();
    builder_main();
}
