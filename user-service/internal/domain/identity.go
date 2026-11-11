package domain

import (
	"time"
)

var ErrUnauthenticated = &Error{Kind: Unauthenticated, Code: "authentication_required"}

// User represents a user account
type User struct {
	ID     string
	Email  string
	Name   string
	Active bool
}

// CanLogin expresses the login rule
func (u User) CanLogin(passwordMatches bool) bool {
	return u.Active && passwordMatches
}

// Session represents an existing login
type Session struct {
	User      User
	ExpiresAt time.Time
	RevokedAt *time.Time
}

// Authenticate returns the user only while the account and session remain valid.
func (s Session) Authenticate(now time.Time) (User, error) {
	if !s.User.Active || s.RevokedAt != nil || !s.ExpiresAt.After(now) {
		return User{}, ErrUnauthenticated
	}
	return s.User, nil
}
