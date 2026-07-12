package control

import (
	"os"
	"testing"

	"go.uber.org/goleak"
)

func TestMain(m *testing.M) {
	if os.Getenv("NEXUSCODE_CREDENTIALS_STORE") == "" {
		_ = os.Setenv("NEXUSCODE_CREDENTIALS_STORE", "file")
	}
	goleak.VerifyTestMain(m)
}
