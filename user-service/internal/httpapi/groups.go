package httpapi

import (
	"github.com/JeanphiloGong/tsingai-lens/user-service/internal/db"
	"github.com/JeanphiloGong/tsingai-lens/user-service/internal/service"
	"github.com/go-chi/chi/v5"
	"net/http"
	"strings"
)

type GroupResponse struct {
	Code        string `json:"code"`
	Name        string `json:"name"`
	Description string `json:"description"`
	IsSystem    bool   `json:"is_system"`
}
type GroupListResponse struct {
	Items  []GroupResponse `json:"items"`
	Total  int64           `json:"total"`
	Limit  int64           `json:"limit"`
	Offset int64           `json:"offset"`
}
type CreateGroupRequest struct {
	Code        string `json:"code"`
	Name        string `json:"name"`
	Description string `json:"description"`
}

func (h *Handler) ListGroups(w http.ResponseWriter, r *http.Request) {
	if !h.authorizeAdministrator(w, r) {
		return
	}
	limit, offset, ok := parsePage(w, r)
	if !ok {
		return
	}
	queries := db.New(h.Service.Pool)
	rows, err := queries.GroupsPage(r.Context(), db.GroupsPageParams{PageLimit: limit, PageOffset: offset})
	if err != nil {
		writeError(w, err)
		return
	}
	total, err := queries.CountGroups(r.Context())
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
func (h *Handler) CreateGroup(w http.ResponseWriter, r *http.Request) {
	var input CreateGroupRequest
	if !decode(w, r, &input) {
		return
	}
	input.Name = strings.TrimSpace(input.Name)
	if len(input.Code) > 64 || !groupCodePattern.MatchString(input.Code) || !validMetadata(input.Name, input.Description) {
		writeError(w, service.ErrInvalid)
		return
	}
	row, err := h.Service.CreateGroup(r.Context(), readSessionToken(r), input.Code, input.Name, input.Description)
	if err != nil {
		writeError(w, err)
		return
	}
	respond(w, 201, GroupResponse{Code: row.Code, Name: row.Name, Description: row.Description, IsSystem: row.IsSystem})
}
func (h *Handler) UpdateGroup(w http.ResponseWriter, r *http.Request) {
	name, description, ok := decodeMetadataUpdate(w, r)
	if !ok {
		return
	}
	row, err := h.Service.UpdateGroup(r.Context(), readSessionToken(r), chi.URLParam(r, "group_code"), name, description)
	if err != nil {
		writeError(w, err)
		return
	}
	respond(w, 200, GroupResponse{Code: row.Code, Name: row.Name, Description: row.Description, IsSystem: row.IsSystem})
}
func (h *Handler) DeleteGroup(w http.ResponseWriter, r *http.Request) {
	if err := h.Service.DeleteGroup(r.Context(), readSessionToken(r), chi.URLParam(r, "group_code")); err != nil {
		writeError(w, err)
		return
	}
	respond(w, 200, OKResponse{OK: true})
}
