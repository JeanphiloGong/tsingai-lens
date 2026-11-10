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
func authenticatedUser(row db.ResolveRow, now time.Time) (domain.User, error) {
	session := domain.Session{
		User:      domain.User{ID: row.UserID, Email: row.Email, Name: row.DisplayName, Active: row.Active},
		ExpiresAt: row.ExpiresAt.Time,
	}
	if row.RevokedAt.Valid {
		session.RevokedAt = &row.RevokedAt.Time
	}
	return session.Resolve(now)
}
func (s *Service) Resolve(ctx context.Context, sessionToken string) (domain.User, error) {
	if sessionToken == "" {
		return domain.User{}, domain.ErrUnauthenticated
	}
	row, err := db.New(s.Pool).Resolve(ctx, tokenHash(sessionToken))
	if errors.Is(err, pgx.ErrNoRows) {
		return domain.User{}, domain.ErrUnauthenticated
	}
	if err != nil {
		return domain.User{}, err
	}
	return authenticatedUser(row, time.Now())
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
