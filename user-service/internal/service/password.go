package service

import (
	"crypto/hmac"
	"crypto/pbkdf2"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"strconv"
	"strings"
)

// randomID creates 32 cryptographically secure random bytes and converts then into a 64-character hexadecimal string
func randomID() string {
	// allocate space for 32 bytes
	b := make([]byte, 32)

	// fill that space with random bytes
	if _, e := rand.Read(b); e != nil {
		panic(e)
	}

	// convert the random bytes into text
	return hex.EncodeToString(b)
}

// tokenHash tuns an unpredictable session token into a digest for database lookup
func tokenHash(s string) string {
	h := sha256.Sum256([]byte(s))
	return hex.EncodeToString(h[:])
}

// passwordHash turns a human password into a salted, deliberately expensive password hash
func passwordHash(p string) (string, error) {
	// generate a random salt
	salt := make([]byte, 16)

	// fills the slice with secure random bytes
	if _, e := rand.Read(salt); e != nil {
		return "", e
	}

	// Derive bytes using PBKDF2
	digest, e := pbkdf2.Key(sha256.New, p, salt, 600000, 32)

	if e != nil {
		return "", e
	}

	// encode the salt, derived bytes and parameters
	return "pbkdf2_sha256:600000:" + base64.StdEncoding.EncodeToString(salt) + ":" + base64.StdEncoding.EncodeToString(digest), nil
}

// passwordMatches checks whether a submitted password matches a previously stored password hash
func passwordMatches(p, encoded string) bool {
	// divides the stored value into fields
	parts := strings.Split(encoded, ":")
	if len(parts) != 4 || parts[0] != "pbkdf2_sha256" {
		return false
	}

	// parses the second field as an integer
	n, e := strconv.Atoi(parts[1])

	if e != nil || n < 100000 || n > 2000000 {
		return false
	}

	// decodes the salt
	salt, e := base64.StdEncoding.DecodeString(parts[2])
	if e != nil {
		return false
	}

	want, e := base64.StdEncoding.DecodeString(parts[3])
	if e != nil || len(want) != 32 {
		return false
	}

	// derives 32 bytes from the password, salt and iteration count, using SHA-256
	got, e := pbkdf2.Key(sha256.New, p, salt, n, 32)

	return e == nil && hmac.Equal(got, want)
}
