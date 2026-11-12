package domain

import (
	"time"
)

// declares the apckage-level error value returned when a challenge is ineligible
var ErrChallenge = &Error{
	Kind: InvalidInput,
	Code: "invalid_email_proof",
}

// declares the data structure that `Check` later examines
type EmailChallenge struct {
	ID        string
	Email     string
	Purpose   string
	State     string
	ExpiresAt time.Time
	Attempts  int32
}

// Check expresses eligibility; cryptographic comparison remains at the service boundary
func (c EmailChallenge) Check(id, email, purpose string, now time.Time) error {
	if c.ID != id || c.Email != email || c.Purpose != purpose || c.State != "sent" || !c.ExpiresAt.After(now) || c.Attempts >= 5 {
		return ErrChallenge
	}
	return nil
}
