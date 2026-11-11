package service

import (
	"context"
	"errors"
	"github.com/JeanphiloGong/tsingai-lens/user-service/internal/db"
	"github.com/JeanphiloGong/tsingai-lens/user-service/internal/domain"
	"github.com/jackc/pgx/v5"
	"strings"
	"time"
)

func (s *Service) Login(ctx context.Context, email, password string) (domain.User, string, error) {
	var user domain.User
	var sessionToken string
	err := s.transaction(ctx, func(queries *db.Queries) error {
		userRow, err := queries.UserByEmail(ctx, strings.ToLower(strings.TrimSpace(email)))
		if errors.Is(err, pgx.ErrNoRows) {
			return domain.ErrUnauthenticated
		}
		if err != nil {
			return err
		}
		account := domain.User{ID: userRow.UserID, Email: userRow.Email, Name: userRow.DisplayName, Active: userRow.Active}
		if !account.CanLogin(passwordMatches(password, userRow.PasswordHash)) {
			return domain.ErrUnauthenticated
		}
		sessionToken = randomID()
		user = account
		return queries.AddSession(ctx, db.AddSessionParams{TokenHash: tokenHash(sessionToken), UserID: userRow.UserID})
	})
	return user, sessionToken, err
}

// authenticateSessionRow converts persisted state and delegates validity checks to Session.Authenticate.
func authenticateSessionRow(sessionRow db.SessionByTokenHashRow, now time.Time) (domain.User, error) {
	session := domain.Session{
		User:      domain.User{ID: sessionRow.UserID, Email: sessionRow.Email, Name: sessionRow.DisplayName, Active: sessionRow.Active},
		ExpiresAt: sessionRow.ExpiresAt.Time,
	}
	if sessionRow.RevokedAt.Valid {
		session.RevokedAt = &sessionRow.RevokedAt.Time
	}
	return session.Authenticate(now)
}
func (s *Service) Resolve(ctx context.Context, sessionToken string) (domain.User, error) {
	if sessionToken == "" {
		return domain.User{}, domain.ErrUnauthenticated
	}
	sessionRow, err := db.New(s.Pool).SessionByTokenHash(ctx, tokenHash(sessionToken))
	if errors.Is(err, pgx.ErrNoRows) {
		return domain.User{}, domain.ErrUnauthenticated
	}
	if err != nil {
		return domain.User{}, err
	}
	return authenticateSessionRow(sessionRow, time.Now())
}
func (s *Service) Logout(ctx context.Context, sessionToken string) error {
	return db.New(s.Pool).Revoke(ctx, tokenHash(sessionToken))
}

// Bootstrap creates the initial local account, before HTTP is exposed.
func (s *Service) Bootstrap(ctx context.Context, email, password string) error {
	if len(password) < 12 || !strings.Contains(email, "@") {
		return ErrInvalid
	}
	encodedPasswordHash, err := passwordHash(password)
	if err != nil {
		return err
	}
	return s.transaction(ctx, func(queries *db.Queries) error {
		if err := queries.LockBootstrap(ctx); err != nil {
			return err
		}
		userCount, err := queries.CountUsers(ctx)
		if err != nil {
			return err
		}
		if userCount != 0 {
			return ErrConflict
		}
		return queries.AddUser(ctx, db.AddUserParams{UserID: "user_" + randomID()[:24], Email: strings.ToLower(strings.TrimSpace(email)), DisplayName: "Administrator", PasswordHash: encodedPasswordHash})
	})
}

// ChangePassword verifies the current password, stores a replacement, and revokes old sessions.
func (s *Service) ChangePassword(ctx context.Context, sessionToken, oldPassword, newPassword string) error {
	// rejects a new password before starting the transaction if it is too short
	if len(newPassword) < 12 {
		return ErrInvalid
	}

	// delegates the remaining work to a transaction helper
	return s.transaction(ctx, func(queries *db.Queries) error {
		// looks up information associated with the session token
		sessionRow, err := queries.SessionByTokenHash(ctx, tokenHash(sessionToken))
		if errors.Is(err, pgx.ErrNoRows) {
			return domain.ErrUnauthenticated
		}
		if err != nil {
			return err
		}

		// loads the account associated with the located session
		userRow, err := queries.UserByID(ctx, sessionRow.UserID)
		if err != nil {
			return err
		}

		// re-reads the session after the user lookup, using the same context and freshly computed token hash
		sessionRow, err = queries.SessionByTokenHash(ctx, tokenHash(sessionToken))
		if err != nil {
			return err
		}

		// checks the re-read session before accepting the password change
		if _, err = authenticateSessionRow(sessionRow, time.Now()); err != nil {
			return err
		}

		// requires the supplied current password to match the hash stored in the loaded user row
		if !passwordMatches(oldPassword, userRow.PasswordHash) {
			return domain.ErrUnauthenticated
		}

		// prepares the value to store for the accepted new password
		encodedPasswordHash, err := passwordHash(newPassword)
		if err != nil {
			return err
		}

		// attempts to store the new hash for the user identified through the session
		if err = queries.SetPassword(ctx, db.SetPasswordParams{
			UserID:       userRow.UserID,
			PasswordHash: encodedPasswordHash,
		}); err != nil {
			return err
		}

		// asks the queries layer to revoke sessions for the same user whose password was updated
		return queries.RevokeUser(ctx, userRow.UserID)
	})
}
