package httpapi

import (
	"errors"
	"github.com/JeanphiloGong/tsingai-lens/user-service/internal/db"
	"github.com/JeanphiloGong/tsingai-lens/user-service/internal/service"
	"github.com/go-chi/chi/v5"
	"github.com/jackc/pgx/v5"
	"net/http"
	"unicode/utf8"
)

type AdminUserResponse struct {
	UserID      string `json:"user_id"`
	Email       string `json:"email"`
	DisplayName string `json:"display_name"`
	Active      bool   `json:"active"`
}
type AdminUsersResponse struct {
	Items  []AdminUserResponse `json:"items"`
	Total  int64               `json:"total"`
	Limit  int64               `json:"limit"`
	Offset int64               `json:"offset"`
}
type UpdateUserStatusRequest struct {
	Active *bool `json:"active"`
}

func (h *Handler) ListUsers(w http.ResponseWriter, r *http.Request) {
	if !h.authorizeAdministrator(w, r) {
		return
	}
	limit, offset, ok := parsePage(w, r)
	if !ok {
		return
	}
	queries := db.New(h.Service.Pool)
	rows, err := queries.UsersPage(r.Context(), db.UsersPageParams{PageLimit: limit, PageOffset: offset})
	if err != nil {
		writeError(w, err)
		return
	}
	total, err := queries.CountUsers(r.Context())
	if err != nil {
		writeError(w, err)
		return
	}
	items := make([]AdminUserResponse, 0, len(rows))
	for _, row := range rows {
		items = append(items, AdminUserResponse{UserID: row.UserID, Email: row.Email, DisplayName: row.DisplayName, Active: row.Active})
	}
	respond(w, 200, AdminUsersResponse{Items: items, Total: total, Limit: limit, Offset: offset})
}
func validUserPath(w http.ResponseWriter, r *http.Request) bool {
	size := utf8.RuneCountInString(chi.URLParam(r, "user_id"))
	if size < 1 || size > 64 {
		writeError(w, service.ErrInvalid)
		return false
	}
	return true
}
func (h *Handler) UpdateUserStatus(w http.ResponseWriter, r *http.Request) {
	var input UpdateUserStatusRequest
	if !decode(w, r, &input) || !validUserPath(w, r) {
		return
	}
	if input.Active == nil {
		writeError(w, service.ErrInvalid)
		return
	}
	row, err := h.Service.UpdateUserStatus(r.Context(), readSessionToken(r), chi.URLParam(r, "user_id"), *input.Active)
	if err != nil {
		writeError(w, err)
		return
	}
	respond(w, 200, AdminUserResponse{UserID: row.UserID, Email: row.Email, DisplayName: row.DisplayName, Active: row.Active})
}
func (h *Handler) ListUserGroups(w http.ResponseWriter, r *http.Request) {
	if !h.authorizeAdministrator(w, r) || !validUserPath(w, r) {
		return
	}
	limit, offset, ok := parsePage(w, r)
	if !ok {
		return
	}
	userID := chi.URLParam(r, "user_id")
	queries := db.New(h.Service.Pool)
	if _, err := queries.UserByID(r.Context(), userID); err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			err = service.ErrInvalid
		}
		writeError(w, err)
		return
	}
	rows, err := queries.UserGroupsPage(r.Context(), db.UserGroupsPageParams{UserID: userID, PageLimit: limit, PageOffset: offset})
	if err != nil {
		writeError(w, err)
		return
	}
	total, err := queries.CountUserGroups(r.Context(), userID)
	if err != nil {
		writeError(w, err)
		return
	}
	items := make([]GroupResponse, 0, len(rows))
	for _, row := range rows {
		items = append(items, GroupResponse{Code: row.Code, Name: row.Name, Description: row.Description, IsSystem: row.IsSystem})
	}
	respond(w, 200, GroupListResponse{Items: items, Total: total, Limit: limit, Offset: offset})
}
func (h *Handler) GrantUserGroup(w http.ResponseWriter, r *http.Request) {
	if !validUserPath(w, r) {
		return
	}
	if err := h.Service.GrantUserGroup(r.Context(), readSessionToken(r), chi.URLParam(r, "user_id"), chi.URLParam(r, "group_code")); err != nil {
		writeError(w, err)
		return
	}
	respond(w, 200, OKResponse{OK: true})
}
func (h *Handler) RevokeUserGroup(w http.ResponseWriter, r *http.Request) {
	if !validUserPath(w, r) {
		return
	}
	if err := h.Service.RevokeUserGroup(r.Context(), readSessionToken(r), chi.URLParam(r, "user_id"), chi.URLParam(r, "group_code")); err != nil {
		writeError(w, err)
		return
	}
	respond(w, 200, OKResponse{OK: true})
}
