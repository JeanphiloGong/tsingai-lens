package service

import (
	"context"
	"errors"
	"github.com/JeanphiloGong/tsingai-lens/user-service/internal/db"
	"github.com/jackc/pgx/v5"
)

func (s *Service) CreateGroup(ctx context.Context, token, code, name, description string) (db.Group, error) {
	var item db.Group
	err := s.transaction(ctx, func(queries *db.Queries) error {
		if err := queries.LockAdministration(ctx); err != nil {
			return err
		}
		actor, err := requireAdministrator(ctx, queries, token)
		if err != nil {
			return err
		}
		item, err = queries.AddGroup(ctx, db.AddGroupParams{Code: code, Name: name, Description: description})
		if err != nil {
			return catalogWriteError(err, "groups_pkey")
		}
		return preserveAdministratorAndAudit(ctx, queries, actor, "group", code, "group.create", map[string]any{"name": name, "description": description})
	})
	return item, err
}
func (s *Service) UpdateGroup(ctx context.Context, token, code string, name, description *string) (db.Group, error) {
	var item db.Group
	err := s.transaction(ctx, func(queries *db.Queries) error {
		if err := queries.LockAdministration(ctx); err != nil {
			return err
		}
		actor, err := requireAdministrator(ctx, queries, token)
		if err != nil {
			return err
		}
		item, err = queries.GroupByCode(ctx, code)
		if errors.Is(err, pgx.ErrNoRows) {
			return ErrInvalidReference
		}
		if err != nil {
			return err
		}
		details := map[string]any{}
		if name != nil {
			item.Name = *name
			details["name"] = *name
		}
		if description != nil {
			item.Description = *description
			details["description"] = *description
		}
		item, err = queries.UpdateGroup(ctx, db.UpdateGroupParams{Code: code, Name: item.Name, Description: item.Description})
		if err != nil {
			return err
		}
		return preserveAdministratorAndAudit(ctx, queries, actor, "group", code, "group.update", details)
	})
	return item, err
}
func (s *Service) DeleteGroup(ctx context.Context, token, code string) error {
	return s.transaction(ctx, func(queries *db.Queries) error {
		if err := queries.LockAdministration(ctx); err != nil {
			return err
		}
		actor, err := requireAdministrator(ctx, queries, token)
		if err != nil {
			return err
		}
		item, err := queries.GroupByCode(ctx, code)
		if errors.Is(err, pgx.ErrNoRows) {
			return ErrInvalidReference
		}
		if err != nil {
			return err
		}
		if item.IsSystem {
			return ErrForbidden
		}
		count, err := queries.CountGroupUsers(ctx, code)
		if err != nil {
			return err
		}
		if count > 0 {
			return ErrConflict
		}
		if err = queries.RemoveGroupPermissions(ctx, code); err != nil {
			return err
		}
		if err = queries.DeleteGroup(ctx, code); err != nil {
			return err
		}
		return preserveAdministratorAndAudit(ctx, queries, actor, "group", code, "group.delete", map[string]any{})
	})
}

func (s *Service) CreatePermission(ctx context.Context, token, code, name, description string) (db.Permission, error) {
	var item db.Permission
	err := s.transaction(ctx, func(queries *db.Queries) error {
		if err := queries.LockAdministration(ctx); err != nil {
			return err
		}
		actor, err := requireAdministrator(ctx, queries, token)
		if err != nil {
			return err
		}
		item, err = queries.AddPermission(ctx, db.AddPermissionParams{Code: code, Name: name, Description: description})
		if err != nil {
			return catalogWriteError(err, "permissions_pkey")
		}
		return preserveAdministratorAndAudit(ctx, queries, actor, "permission", code, "permission.create", map[string]any{"name": name, "description": description})
	})
	return item, err
}
func (s *Service) UpdatePermission(ctx context.Context, token, code string, name, description *string) (db.Permission, error) {
	var item db.Permission
	err := s.transaction(ctx, func(queries *db.Queries) error {
		if err := queries.LockAdministration(ctx); err != nil {
			return err
		}
		actor, err := requireAdministrator(ctx, queries, token)
		if err != nil {
			return err
		}
		item, err = queries.PermissionByCode(ctx, code)
		if errors.Is(err, pgx.ErrNoRows) {
			return ErrInvalidReference
		}
		if err != nil {
			return err
		}
		details := map[string]any{}
		if name != nil {
			item.Name = *name
			details["name"] = *name
		}
		if description != nil {
			item.Description = *description
			details["description"] = *description
		}
		item, err = queries.UpdatePermission(ctx, db.UpdatePermissionParams{Code: code, Name: item.Name, Description: item.Description})
		if err != nil {
			return err
		}
		return preserveAdministratorAndAudit(ctx, queries, actor, "permission", code, "permission.update", details)
	})
	return item, err
}
func (s *Service) DeletePermission(ctx context.Context, token, code string) error {
	return s.transaction(ctx, func(queries *db.Queries) error {
		if err := queries.LockAdministration(ctx); err != nil {
			return err
		}
		actor, err := requireAdministrator(ctx, queries, token)
		if err != nil {
			return err
		}
		item, err := queries.PermissionByCode(ctx, code)
		if errors.Is(err, pgx.ErrNoRows) {
			return ErrInvalidReference
		}
		if err != nil {
			return err
		}
		if item.IsSystem {
			return ErrForbidden
		}
		count, err := queries.CountPermissionGroups(ctx, code)
		if err != nil {
			return err
		}
		if count > 0 {
			return ErrConflict
		}
		if err = queries.DeletePermission(ctx, code); err != nil {
			return err
		}
		return preserveAdministratorAndAudit(ctx, queries, actor, "permission", code, "permission.delete", map[string]any{})
	})
}

func (s *Service) GrantGroupPermission(ctx context.Context, token, groupCode, permissionCode string) error {
	return s.transaction(ctx, func(queries *db.Queries) error {
		if err := queries.LockAdministration(ctx); err != nil {
			return err
		}
		actor, err := requireAdministrator(ctx, queries, token)
		if err != nil {
			return err
		}
		if _, err = queries.GroupByCode(ctx, groupCode); errors.Is(err, pgx.ErrNoRows) {
			return ErrInvalidReference
		}
		if err != nil {
			return err
		}
		if _, err = queries.PermissionByCode(ctx, permissionCode); errors.Is(err, pgx.ErrNoRows) {
			return ErrInvalidReference
		}
		if err != nil {
			return err
		}
		if err = queries.GrantPermission(ctx, db.GrantPermissionParams{GroupCode: groupCode, PermissionCode: permissionCode}); err != nil {
			return err
		}
		return preserveAdministratorAndAudit(ctx, queries, actor, "group", groupCode, "group.permission.grant", map[string]any{"permission_code": permissionCode})
	})
}

func (s *Service) RevokeGroupPermission(ctx context.Context, token, groupCode, permissionCode string) error {
	return s.transaction(ctx, func(queries *db.Queries) error {
		if err := queries.LockAdministration(ctx); err != nil {
			return err
		}
		actor, err := requireAdministrator(ctx, queries, token)
		if err != nil {
			return err
		}
		if _, err = queries.GroupByCode(ctx, groupCode); errors.Is(err, pgx.ErrNoRows) {
			return ErrInvalidReference
		}
		if err != nil {
			return err
		}
		if _, err = queries.PermissionByCode(ctx, permissionCode); errors.Is(err, pgx.ErrNoRows) {
			return ErrInvalidReference
		}
		if err != nil {
			return err
		}
		if err = queries.RevokePermission(ctx, db.RevokePermissionParams{GroupCode: groupCode, PermissionCode: permissionCode}); err != nil {
			return err
		}
		return preserveAdministratorAndAudit(ctx, queries, actor, "group", groupCode, "group.permission.revoke", map[string]any{"permission_code": permissionCode})
	})
}
