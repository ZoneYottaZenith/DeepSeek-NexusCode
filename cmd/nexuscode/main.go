// Command nexuscode is a config- and plugin-driven coding agent CLI.
package main

import (
	"os"

	"nexuscode/internal/cli"

	// Blank imports wire compile-time built-ins into their registries.
	_ "nexuscode/internal/provider/anthropic"
	_ "nexuscode/internal/provider/openai"
	_ "nexuscode/internal/tool/builtin"
)

// version is injected at build time via -ldflags "-X main.version=...".
var version = "dev"

func main() {
	os.Exit(cli.Run(os.Args[1:], version))
}
