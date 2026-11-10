package domain

import (
	"testing"
	"time"
)

func TestIdentityRules(t *testing.T) {
	now := time.Date(2026, 11, 4, 0, 0, 0, 0, time.UTC)
	user := User{ID: "researcher", Active: true}
	if !user.CanLogin(true) || user.CanLogin(false) {
		t.Fatal("login must require a matching password")
	}
	disabled := user
	disabled.Active = false
	if disabled.CanLogin(true) {
		t.Fatal("disabled account cannot log in")
	}
	for _, tc := range []struct {
		name    string
		session Session
		allowed bool
	}{
		{"valid", Session{User: user, ExpiresAt: now.Add(time.Hour)}, true},
		{"disabled", Session{User: disabled, ExpiresAt: now.Add(time.Hour)}, false},
		{"expires now", Session{User: user, ExpiresAt: now}, false},
		{"revoked", Session{User: user, ExpiresAt: now.Add(time.Hour), RevokedAt: &now}, false},
	} {
		t.Run(tc.name, func(t *testing.T) {
			got, err := tc.session.Resolve(now)
			if tc.allowed {
				if err != nil || got.ID != user.ID {
					t.Fatalf("identity: %+v, %v", got, err)
				}
			} else if err != ErrUnauthenticated {
				t.Fatalf("expected authentication rejection, got %v", err)
			}
		})
	}
}
