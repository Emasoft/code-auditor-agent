// Fixture exercising the two Go CLI idioms the discoverer must handle:
//  1. spf13/cobra — &cobra.Command{Use: "...", Short: "...", Run: ...}
//     with `rootCmd.AddCommand(fooCmd)` chains.
//  2. urfave/cli — &cli.Command{Name: "...", Usage: "..."} literals.
//
// kingpin is also recognised by the discoverer but not used in this
// fixture (we want each fixture to test one primary framework deeply).
package main

import (
	"fmt"

	"github.com/spf13/cobra"
)

// We import urfave/cli only inside a helper so this fixture file
// exercises both literal forms without forcing two binaries.
type cliCommand struct {
	Name        string
	Usage       string
	Description string
}

// Pretend `cli.Command` is the urfave alias so the literal below matches
// the discoverer's regex without requiring real go module resolution.
var cli = struct {
	Command cliCommand
}{}

var rootCmd = &cobra.Command{
	Use:   "fixture-cli",
	Short: "Test fixture for the cli_go discoverer.",
	Long:  "Top-level cobra command — exercises the cobra.Command literal idiom.",
}

var greetCmd = &cobra.Command{
	Use:   "greet [name]",
	Short: "Print a friendly greeting to the named user.",
	Run: func(cmd *cobra.Command, args []string) {
		if len(args) == 0 {
			fmt.Println("hello world")
			return
		}
		fmt.Printf("hello %s\n", args[0])
	},
}

var goodbyeCmd = &cobra.Command{
	Use:   "goodbye [user]",
	Short: "Wave goodbye to the named user before exiting.",
	Run: func(cmd *cobra.Command, args []string) {
		who := "world"
		if len(args) > 0 {
			who = args[0]
		}
		fmt.Printf("goodbye %s\n", who)
	},
}

// urfave/cli object form — recognised by the discoverer alongside cobra
// in the same file. The fixture uses a shim so the file compiles.
var urfaveCmd = cli.Command{
	Name:  "sync",
	Usage: "Copy files between two locations on disk.",
}

func main() {
	rootCmd.AddCommand(greetCmd)
	rootCmd.AddCommand(goodbyeCmd)
	_ = urfaveCmd
	if err := rootCmd.Execute(); err != nil {
		fmt.Println(err)
	}
}
