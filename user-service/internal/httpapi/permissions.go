package httpapi

import (
	"encoding/json"
	"errors"
	"github.com/JeanphiloGong/tsingai-lens/user-service/internal/db"
	"github.com/JeanphiloGong/tsingai-lens/user-service/internal/service"
	"github.com/go-chi/chi/v5"
	"github.com/jackc/pgx/v5"
	"net/http"
	"regexp"
	"strconv"
	"strings"
	"unicode/utf8"
)

type PermissionsResponse struct {
	PermissionCodes []string `json:"permission_codes"`
}
type PermissionResponse struct {
	Code        string `json:"code"`
	Name        string `json:"name"`
	Description string `json:"description"`
	IsSystem    bool   `json:"is_system"`
}
type PermissionListResponse struct {
	Items  []PermissionResponse `json:"items"`
	Total  int64                `json:"total"`
	Limit  int64                `json:"limit"`
	Offset int64                `json:"offset"`
}
type CreatePermissionRequest struct {
	Code        string `json:"code"`
	Name        string `json:"name"`
	Description string `json:"description"`
}

// Both catalog updates share this exact HTTP shape. RawMessage distinguishes
// an omitted field from explicit null before values reach the service.
type MetadataUpdateRequest struct {
	Name        json.RawMessage `json:"name"`
	Description json.RawMessage `json:"description"`
}

var permissionCodePattern = regexp.MustCompile(`^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$`)
var groupCodePattern = regexp.MustCompile(`^[a-z][a-z0-9_]*$`)

func (h *Handler) CurrentPermissions(w http.ResponseWriter, r *http.Request) {
	user, err := h.Service.Resolve(r.Context(), readSessionToken(r))
	if err != nil {
		writeError(w, err)
		return
	}
	codes, err := h.Service.Permissions(r.Context(), user.ID)
	if err != nil {
		writeError(w, err)
		return
	}
	if codes == nil {
		codes = []string{}
	}
	respond(w, 200, PermissionsResponse{PermissionCodes: codes})
}

// Read handlers authorize before looking up targets. Write use cases perform
// their own authorization under the administration transaction lock.
func (h *Handler) authorizeAdministrator(w http.ResponseWriter, r *http.Request) bool {
	user, err := h.Service.Resolve(r.Context(), readSessionToken(r))
	if err != nil {
		writeError(w, err)
		return false
	}
	allowed, err := h.Service.Check(r.Context(), user.ID, "users.manage")
	if err != nil {
		writeError(w, err)
		return false
	}
	if !allowed {
		writeError(w, service.ErrForbidden)
		return false
	}
	return true
}
func parsePage(w http.ResponseWriter, r *http.Request) (int64, int64, bool) {
	limit, offset := int64(50), int64(0)
	var err error
	if values, ok := r.URL.Query()["limit"]; ok {
		limit, err = strconv.ParseInt(values[0], 10, 64)
		if err != nil || limit < 1 || limit > 200 {
			writeError(w, service.ErrInvalid)
			return 0, 0, false
		}
	}
	if values, ok := r.URL.Query()["offset"]; ok {
		offset, err = strconv.ParseInt(values[0], 10, 64)
		if err != nil || offset < 0 {
			writeError(w, service.ErrInvalid)
			return 0, 0, false
		}
	}
	return limit, offset, true
}
func validMetadata(name, description string) bool {
	size := utf8.RuneCountInString(name)
	return size >= 1 && size <= 100 && utf8.RuneCountInString(description) <= 1000
}
func decodeMetadataUpdate(w http.ResponseWriter, r *http.Request) (*string, *string, bool) {
	var input MetadataUpdateRequest
	if !decode(w, r, &input) {
		return nil, nil, false
	}
	if input.Name == nil && input.Description == nil {
		writeError(w, service.ErrInvalid)
		return nil, nil, false
	}
	var name, description *string
	if input.Name != nil {
		var value *string
		if json.Unmarshal(input.Name, &value) != nil || value == nil {
			writeError(w, service.ErrInvalid)
			return nil, nil, false
		}
		trimmed := strings.TrimSpace(*value)
		if !validMetadata(trimmed, "") {
			writeError(w, service.ErrInvalid)
			return nil, nil, false
		}
		name = &trimmed
	}
	if input.Description != nil {
		if json.Unmarshal(input.Description, &description) != nil || description == nil || utf8.RuneCountInString(*description) > 1000 {
			writeError(w, service.ErrInvalid)
			return nil, nil, false
		}
	}
	return name, description, true
}
func (h *Handler) ListPermissions(w http.ResponseWriter, r *http.Request) {
	if !h.authorizeAdministrator(w, r) {
		return
	}
	limit, offset, ok := parsePage(w, r)
	if !ok {
		return
	}
	queries := db.New(h.Service.Pool)
	rows, err := queries.PermissionsPage(r.Context(), db.PermissionsPageParams{PageLimit: limit, PageOffset: offset})
	if err != nil {
		writeError(w, err)
		return
	}
	total, err := queries.CountPermissions(r.Context())
	if err != nil {
		writeError(w, err)
		return
	}
	items := make([]PermissionResponse, 0, len(rows))
	for _, row := range rows {
		items = append(items, PermissionResponse{Code: row.Code, Name: row.Name, Description: row.Description, IsSystem: row.IsSystem})
	}
	respond(w, 200, PermissionListResponse{Items: items, Total: total, Limit: limit, Offset: offset})
}
func (h *Handler) CreatePermission(w http.ResponseWriter, r *http.Request) {
	var input CreatePermissionRequest
	if !decode(w, r, &input) {
		return
	}
	input.Name = strings.TrimSpace(input.Name)
	if len(input.Code) > 128 || !permissionCodePattern.MatchString(input.Code) || !validMetadata(input.Name, input.Description) {
		writeError(w, service.ErrInvalid)
		return
	}
	row, err := h.Service.CreatePermission(r.Context(), readSessionToken(r), input.Code, input.Name, input.Description)
	if err != nil {
		writeError(w, err)
		return
	}
	respond(w, 201, PermissionResponse{Code: row.Code, Name: row.Name, Description: row.Description, IsSystem: row.IsSystem})
}
func (h *Handler) UpdatePermission(w http.ResponseWriter, r *http.Request) {
	name, description, ok := decodeMetadataUpdate(w, r)
	if !ok {
		return
	}
	row, err := h.Service.UpdatePermission(r.Context(), readSessionToken(r), chi.URLParam(r, "permission_code"), name, description)
	if err != nil {
		writeError(w, err)
		return
	}
	respond(w, 200, PermissionResponse{Code: row.Code, Name: row.Name, Description: row.Description, IsSystem: row.IsSystem})
}
func (h *Handler) DeletePermission(w http.ResponseWriter, r *http.Request) {
	if err := h.Service.DeletePermission(r.Context(), readSessionToken(r), chi.URLParam(r, "permission_code")); err != nil {
		writeError(w, err)
		return
	}
	respond(w, 200, OKResponse{OK: true})
}
func (h *Handler) ListGroupPermissions(w http.ResponseWriter, r *http.Request) {
	if !h.authorizeAdministrator(w, r) {
		return
	}
	limit, offset, ok := parsePage(w, r)
	if !ok {
		return
	}
	code := chi.URLParam(r, "group_code")
	queries := db.New(h.Service.Pool)
	if _, err := queries.GroupByCode(r.Context(), code); err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			err = service.ErrInvalidReference
		}
		writeError(w, err)
		return
	}
	rows, err := queries.GroupPermissionsPage(r.Context(), db.GroupPermissionsPageParams{GroupCode: code, PageLimit: limit, PageOffset: offset})
	if err != nil {
		writeError(w, err)
		return
	}
	total, err := queries.CountGroupPermissions(r.Context(), code)
	if err != nil {
		writeError(w, err)
		return
	}
	items := make([]PermissionResponse, 0, len(rows))
	for _, row := range rows {
		items = append(items, PermissionResponse{Code: row.Code, Name: row.Name, Description: row.Description, IsSystem: row.IsSystem})
	}
	respond(w, 200, PermissionListResponse{Items: items, Total: total, Limit: limit, Offset: offset})
}
func (h *Handler) GrantGroupPermission(w http.ResponseWriter, r *http.Request) {
	if err := h.Service.GrantGroupPermission(r.Context(), readSessionToken(r), chi.URLParam(r, "group_code"), chi.URLParam(r, "permission_code")); err != nil {
		writeError(w, err)
		return
	}
	respond(w, 200, OKResponse{OK: true})
}
func (h *Handler) RevokeGroupPermission(w http.ResponseWriter, r *http.Request) {
	if err := h.Service.RevokeGroupPermission(r.Context(), readSessionToken(r), chi.URLParam(r, "group_code"), chi.URLParam(r, "permission_code")); err != nil {
		writeError(w, err)
		return
	}
	respond(w, 200, OKResponse{OK: true})
}
