package config

import (
	"path/filepath"
	"testing"
)

func TestExpandVars(t *testing.T) {
	t.Setenv("NEXUSCODE_TEST_TOKEN", "sk-123")
	t.Setenv("NEXUSCODE_TEST_EMPTY", "")

	cases := []struct{ in, want string }{
		{"Bearer ${NEXUSCODE_TEST_TOKEN}", "Bearer sk-123"},
		{"${NEXUSCODE_TEST_MISSING}", ""},                                   // unset, no default → empty
		{"${NEXUSCODE_TEST_MISSING:-fallback}", "fallback"},                 // unset → default
		{"${NEXUSCODE_TEST_EMPTY:-fallback}", "fallback"},                   // set-but-empty → default
		{"${NEXUSCODE_TEST_TOKEN:-fallback}", "sk-123"},                     // set → value, default ignored
		{"no vars here", "no vars here"},                                   // untouched
		{"a${NEXUSCODE_TEST_TOKEN}b${NEXUSCODE_TEST_MISSING}c", "ask-123bc"}, // multiple refs
	}
	for _, c := range cases {
		if got := ExpandVars(c.in); got != c.want {
			t.Errorf("ExpandVars(%q) = %q, want %q", c.in, got, c.want)
		}
	}
}

func TestExpandedPlugin(t *testing.T) {
	t.Setenv("NEXUSCODE_TEST_KEY", "secret")
	e := PluginEntry{
		Name:    "x",
		Type:    "http",
		URL:     "https://api/${NEXUSCODE_TEST_MISSING:-v1}",
		Args:    []string{"--token", "${NEXUSCODE_TEST_KEY}"},
		Env:     map[string]string{"K": "${NEXUSCODE_TEST_KEY}"},
		Headers: map[string]string{"Authorization": "Bearer ${NEXUSCODE_TEST_KEY}"},
	}
	out := e.ExpandedPlugin()
	if out.URL != "https://api/v1" {
		t.Errorf("URL = %q", out.URL)
	}
	if out.Args[1] != "secret" {
		t.Errorf("Args = %v", out.Args)
	}
	if out.Env["K"] != "secret" || out.Headers["Authorization"] != "Bearer secret" {
		t.Errorf("env/headers not expanded: %v %v", out.Env, out.Headers)
	}
	// The original entry must be untouched (we returned a copy).
	if e.Headers["Authorization"] != "Bearer ${NEXUSCODE_TEST_KEY}" {
		t.Error("ExpandedPlugin mutated the original entry")
	}
}

func TestForbidReadRootsForRootResolvesRelativePathsAndScopedEnv(t *testing.T) {
	root := t.TempDir()
	cfg := Default()
	cfg.setExpansionEnv(map[string]string{"NEXUSCODE_TEST_SECRET_DIR": "from-dotenv"})
	cfg.Sandbox.ForbidRead = []string{
		"relative-secret",
		"${NEXUSCODE_TEST_SECRET_DIR}",
		filepath.Join(root, "absolute-secret"),
	}

	got := cfg.ForbidReadRootsForRoot(root)
	want := []string{
		filepath.Join(root, "relative-secret"),
		filepath.Join(root, "from-dotenv"),
		filepath.Join(root, "absolute-secret"),
	}
	if len(got) != len(want) {
		t.Fatalf("ForbidReadRootsForRoot returned %d roots, want %d: %v", len(got), len(want), got)
	}
	for i := range want {
		if got[i] != want[i] {
			t.Fatalf("root %d = %q, want %q (all roots: %v)", i, got[i], want[i], got)
		}
	}
}

func TestWriteRootsForRootExpandsMavenAllowWrite(t *testing.T) {
	home := t.TempDir()
	project := t.TempDir()
	t.Setenv("HOME", home)

	cfg := Default()
	cfg.Sandbox.AllowWrite = []string{
		"${HOME}/.m2",
		"${HOME}/.m2/repository",
	}

	got := cfg.WriteRootsForRoot(project)
	// WriteRootsForRoot expands variables but leaves configured separators intact;
	// the writer confiner normalizes roots later.
	want := []string{
		project,
		home + "/.m2",
		home + "/.m2/repository",
	}
	if len(got) != len(want) {
		t.Fatalf("WriteRootsForRoot() returned %d roots, want %d: %v", len(got), len(want), got)
	}
	for i := range want {
		if got[i] != want[i] {
			t.Fatalf("root %d = %q, want %q (all roots: %v)", i, got[i], want[i], got)
		}
	}
}
