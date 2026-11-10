package service

import (
	"strings"
	"testing"
)

func TestPasswordRoundTrip(t *testing.T) {
	encoded, err := passwordHash("tutorial-only-password")
	if err != nil {
		t.Fatal(err)
	}
	if !passwordMatches("tutorial-only-password", encoded) || passwordMatches("wrong", encoded) {
		t.Fatal("password matching contract")
	}
	if passwordMatches("tutorial-only-password", "invalid") {
		t.Fatal("invalid imported encoding must not authenticate")
	}
	second, err := passwordHash("tutorial-only-password")
	if err != nil || second == encoded {
		t.Fatal("identical passwords must receive independent random salts")
	}
	parts := strings.Split(encoded, ":")
	for _, invalid := range []string{
		"pbkdf_sha256:" + strings.Join(parts[1:], ":"),
		"pbkdf2_sha256:99999:" + strings.Join(parts[2:], ":"),
		"pbkdf2_sha256:2000001:" + strings.Join(parts[2:], ":"),
		"pbkdf2_sha256:600000:not-base64:" + parts[3],
		"pbkdf2_sha256:600000:" + parts[2] + ":c2hvcnQ=",
	} {
		if passwordMatches("tutorial-only-password", invalid) {
			t.Fatal("malformed or unsupported stored credential authenticated")
		}
	}
}
