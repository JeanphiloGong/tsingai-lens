package service

import (
	"context"
	"errors"
	"github.com/JeanphiloGong/tsingai-lens/user-service/internal/db"
	"github.com/jackc/pgx/v5"
)

func (s *Service) UpdateUserStatus(ctx context.Context, token, userID string, active bool) (db.User, error) {
	var user db.User
	err := s.transaction(ctx, func(queries *db.Queries) error {
		if err := queries.LockAdministration(ctx); err != nil {
			return err
		}
		actor, err := requireAdministrator(ctx, queries, token)
		if err != nil {
			return err
		}
		user, err = queries.UserByID(ctx, userID)
		if errors.Is(err, pgx.ErrNoRows) {
			return ErrInvalid
		}
		if err != nil {
			return err
		}
		if err = queries.SetActive(ctx, db.SetActiveParams{UserID: userID, Active: active}); err != nil {
			return err
		}
		if !active {
			if err = queries.RevokeUser(ctx, userID); err != nil {
				return err
			}
		}
		user.Active = active
		return preserveAdministratorAndAudit(ctx, queries, actor, "user", userID, "user.status.update", map[string]any{"active": active})
	})
	return user, err
}

func (s *Service) GrantUserGroup(ctx context.Context, token, userID, groupCode string) error {
	return s.transaction(ctx, func(queries *db.Queries) error {
		if err := queries.LockAdministration(ctx); err != nil {
			return err
		}
		actor, err := requireAdministrator(ctx, queries, token)
		if err != nil {
			return err
		}
		if _, err = queries.UserByID(ctx, userID); errors.Is(err, pgx.ErrNoRows) {
			return ErrInvalid
		}
		if err != nil {
			return err
		}
		if _, err = queries.GroupByCode(ctx, groupCode); errors.Is(err, pgx.ErrNoRows) {
			return ErrInvalidReference
		}
		if err != nil {
			return err
		}
		if err = queries.GrantGroup(ctx, db.GrantGroupParams{UserID: userID, GroupCode: groupCode}); err != nil {
			return err
		}
		return preserveAdministratorAndAudit(ctx, queries, actor, "user", userID, "user.group.grant", map[string]any{"group_code": groupCode})
	})
}

func (s *Service) RevokeUserGroup(ctx context.Context, token, userID, groupCode string) error {
	return s.transaction(ctx, func(queries *db.Queries) error {
		if err := queries.LockAdministration(ctx); err != nil {
			return err
		}
		actor, err := requireAdministrator(ctx, queries, token)
		if err != nil {
			return err
		}
		if _, err = queries.UserByID(ctx, userID); errors.Is(err, pgx.ErrNoRows) {
			return ErrInvalid
		}
		if err != nil {
			return err
		}
		if _, err = queries.GroupByCode(ctx, groupCode); errors.Is(err, pgx.ErrNoRows) {
			return ErrInvalidReference
		}
		if err != nil {
			return err
		}
		if err = queries.RevokeGroup(ctx, db.RevokeGroupParams{UserID: userID, GroupCode: groupCode}); err != nil {
			return err
		}
		return preserveAdministratorAndAudit(ctx, queries, actor, "user", userID, "user.group.revoke", map[string]any{"group_code": groupCode})
	})
}
