package service

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"github.com/JeanphiloGong/tsingai-lens/user-service/internal/db"
	"github.com/JeanphiloGong/tsingai-lens/user-service/internal/domain"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"
	"slices"
	"strings"
	"time"
)

var ErrAlreadyExists = &domain.Error{Kind: domain.Conflict, Code: "already_exists"}
var ErrInvalidReference = &domain.Error{Kind: domain.InvalidInput, Code: "invalid_reference"}

func (s *Service) InitializeAdmin(ctx context.Context, email string) error {
	return s.transaction(ctx, func(queries *db.Queries) error {
		if err := queries.LockAdministration(ctx); err != nil {
			return err
		}
		count, err := queries.CountAdmins(ctx)
		if err != nil {
			return err
		}
		if count != 0 {
			return ErrConflict
		}
		user, err := queries.UserByEmail(ctx, strings.ToLower(strings.TrimSpace(email)))
		if err != nil {
			return err
		}
		if !user.Active {
			return ErrInvalid
		}
		if err = queries.GrantGroup(ctx, db.GrantGroupParams{UserID: user.UserID, GroupCode: "admin"}); err != nil {
			return err
		}
		return preserveAdministratorAndAudit(ctx, queries, user.UserID, "user", user.UserID, "initialize_admin", map[string]any{})
	})
}

func (s *Service) Permissions(ctx context.Context, userID string) ([]string, error) {
	return db.New(s.Pool).ListPermissions(ctx, userID)
}
func (s *Service) Check(ctx context.Context, userID, code string) (bool, error) {
	codes, err := s.Permissions(ctx, userID)
	return slices.Contains(codes, code), err
}

// requireAdministrator runs after the administration lock. It locks and rechecks
// the actor so a credential change while waiting cannot authorize this write.
func requireAdministrator(ctx context.Context, queries *db.Queries, token string) (string, error) {
	row, err := queries.SessionByTokenHash(ctx, tokenHash(token))
	if errors.Is(err, pgx.ErrNoRows) {
		return "", domain.ErrUnauthenticated
	}
	if err != nil {
		return "", err
	}
	if _, err = queries.UserByID(ctx, row.UserID); err != nil {
		return "", err
	}
	row, err = queries.SessionByTokenHash(ctx, tokenHash(token))
	if err != nil {
		return "", err
	}
	if _, err = authenticateSessionRow(row, time.Now()); err != nil {
		return "", err
	}
	codes, err := queries.ListPermissions(ctx, row.UserID)
	if err != nil {
		return "", err
	}
	if !slices.Contains(codes, "users.manage") {
		return "", ErrForbidden
	}
	return row.UserID, nil
}

// preserveAdministratorAndAudit checks the postcondition and saves the event
// using the caller's transaction. It neither starts nor commits a transaction.
func preserveAdministratorAndAudit(ctx context.Context, queries *db.Queries, actor, kind, target, action string, details map[string]any) error {
	count, err := queries.CountAdmins(ctx)
	if err != nil {
		return err
	}
	if count == 0 {
		return ErrConflict
	}
	encoded, err := json.Marshal(details)
	if err != nil {
		return err
	}
	return queries.Audit(ctx, db.AuditParams{ActorID: actor, TargetType: kind, TargetID: target, Action: action, Details: encoded})
}
func catalogWriteError(err error, constraint string) error {
	var databaseError *pgconn.PgError
	if errors.As(err, &databaseError) && databaseError.Code == "23505" && databaseError.ConstraintName == constraint {
		return fmt.Errorf("catalog code: %w: %w", ErrAlreadyExists, err)
	}
	return err
}
