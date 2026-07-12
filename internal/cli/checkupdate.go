package cli

import (
	"encoding/json"
	"fmt"
	"log/slog"
	"net/http"
	"os"
	"time"

	"golang.org/x/mod/semver"
)

// cliVersion stores the binary version string, set at startup by Run().
var cliVersion string

// npmRegistryURL is the npm registry JSON endpoint for latest version.
const npmRegistryURL = "https://registry.npmjs.org/nexuscode/latest"

const npmCheckTimeout = 5 * time.Second

// npmResponse is the subset of the npm registry response we need.
type npmResponse struct {
	Version string `json:"version"`
}

// checkNPMUpdate fetches the latest version from npm registry and prints a hint
// when a newer release is available. It is intended to run as a background
// goroutine so it never blocks startup.
func checkNPMUpdate() {
	if cliVersion == "" || cliVersion == "dev" {
		return // dev builds don't check
	}
	if !semver.IsValid("v" + cliVersion) {
		return // not a semver tag, skip
	}

	client := &http.Client{Timeout: npmCheckTimeout}
	resp, err := client.Get(npmRegistryURL)
	if err != nil {
		slog.Debug("npm update check failed", "error", err)
		return
	}
	defer resp.Body.Close()

	var data npmResponse
	if err := json.NewDecoder(resp.Body).Decode(&data); err != nil {
		slog.Debug("npm update check: decode failed", "error", err)
		return
	}
	if data.Version == "" {
		return
	}
	latest := "v" + data.Version
	if !semver.IsValid(latest) {
		return
	}
	if semver.Compare(latest, "v"+cliVersion) > 0 {
		fmt.Fprintf(os.Stderr, "\n  ⇡ 新版本 %s 可用，运行 "+
			"npm i -g nexuscode 更新（当前版本 %s）\n\n", data.Version, cliVersion)
	}
}
