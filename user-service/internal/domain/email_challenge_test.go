package domain

import (
	"testing"
	"time"
)

func TestEmailProof(t *testing.T) {
	now := time.Date(2026, 11, 5, 0, 0, 0, 0, time.UTC)
	valid := EmailChallenge{ID: "proof", Email: "a@example.test", Purpose: "register", State: "sent", ExpiresAt: now.Add(time.Minute)}
	if valid.Check("proof", "a@example.test", "register", now) != nil {
		t.Fatal("valid proof rejected")
	}
	for _, change := range []func(*EmailChallenge){
		func(c *EmailChallenge) { c.ID = "other" }, func(c *EmailChallenge) { c.Email = "b@example.test" },
		func(c *EmailChallenge) { c.Purpose = "password_reset" }, func(c *EmailChallenge) { c.State = "pending" },
		func(c *EmailChallenge) { c.State = "consumed" }, func(c *EmailChallenge) { c.ExpiresAt = now },
		func(c *EmailChallenge) { c.Attempts = 5 },
	} {
		c := valid
		change(&c)
		if c.Check("proof", "a@example.test", "register", now) != ErrChallenge {
			t.Fatalf("accepted %+v", c)
		}
	}
}
