// Fixture exercising the two C# CLI idioms the discoverer must handle:
//   1. System.CommandLine — new RootCommand("...") + new Command("...", "...").
//   2. CommandLineParser — [Verb("...", HelpText = "...")] attributes
//      annotating verb classes.
using System.CommandLine;
using CommandLine;

namespace FixtureCli;

public class Program
{
    public static int Main(string[] args)
    {
        var root = new RootCommand("Test fixture for the cli_csharp discoverer.");
        var greet = new Command("greet", "Print a friendly greeting to the named user.");
        var goodbye = new Command("goodbye", "Wave goodbye to the named user before exiting.");
        root.AddCommand(greet);
        root.AddCommand(goodbye);
        return root.Invoke(args);
    }
}

// CommandLineParser style — each verb class carries a [Verb] attribute.
[Verb("sync", HelpText = "Copy files between two locations on disk.")]
public class SyncOptions
{
    public string? Src { get; set; }
    public string? Dst { get; set; }
}

[Verb("status", HelpText = "Print current status to stdout.")]
public class StatusOptions
{
}
