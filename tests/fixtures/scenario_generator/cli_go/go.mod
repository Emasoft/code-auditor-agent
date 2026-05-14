// fixture for cli_go — fingerprint requires main.go with `package main`
// plus `github.com/spf13/cobra` (or urfave/kingpin/flag.Parse) markers
// in a *.go file.
module github.com/example/go-fixture-cli

go 1.22

require github.com/spf13/cobra v1.8.0
