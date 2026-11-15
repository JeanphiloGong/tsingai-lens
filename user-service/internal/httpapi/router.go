package httpapi

import (
	"encoding/json"
	"errors"
	"github.com/JeanphiloGong/tsingai-lens/user-service/internal/service"
	"github.com/go-chi/chi/v5"
	"io"
	"net"
	"net/http"
)

type OKResponse struct {
	OK bool `json:"ok"`
}

type ErrorResponse struct {
	Code       string `json:"code"`
	RetryAfter int    `json:"retry_after,omitempty"`
}

func respond(w http.ResponseWriter, statusCode int, responseBody any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(statusCode)
	json.NewEncoder(w).Encode(responseBody)
}
func decode(w http.ResponseWriter, r *http.Request, destination any) bool {
	r.Body = http.MaxBytesReader(w, r.Body, 8192)
	decoder := json.NewDecoder(r.Body)
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(destination); err != nil {
		writeError(w, service.ErrInvalid)
		return false
	}
	var trailing any
	if err := decoder.Decode(&trailing); !errors.Is(err, io.EOF) {
		writeError(w, service.ErrInvalid)
		return false
	}
	return true
}

func clientIP(r *http.Request, trustedProxy string) string {
	host, _, err := net.SplitHostPort(r.RemoteAddr)
	if err != nil {
		return r.RemoteAddr
	}
	if trustedProxy != "" && host == trustedProxy {
		if ip := net.ParseIP(r.Header.Get("X-Real-IP")); ip != nil {
			return ip.String()
		}
	}
	return host
}

func Router(s *service.Service, origin string, secure bool, trustedProxy string) http.Handler {
	router := chi.NewRouter()
	router.Use(func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			w.Header().Set("Cache-Control", "no-store")
			// Reject cross-origin writes including login; browser clients send Origin.
			if r.Method != "GET" && r.Method != "HEAD" && r.Header.Get("Origin") != origin {
				writeError(w, service.ErrForbidden)
				return
			}
			next.ServeHTTP(w, r)
		})
	})
	handler := &Handler{Service: s, SecureCookie: secure, TrustedProxy: trustedProxy}
	router.Get("/ready", handler.Ready)
	router.Post("/v1/login", handler.Login)
	router.Post("/v1/logout", handler.Logout)
	router.Get("/v1/me", handler.CurrentUser)
	router.Post("/v1/me/password", handler.ChangePassword)
	router.Post("/v1/email-challenges", handler.SendEmailCode)
	router.Post("/v1/register", handler.Register)
	router.Post("/v1/password-resets", handler.ResetPassword)

	router.Get("/v1/me/permissions", handler.CurrentPermissions)
	router.Get("/v1/admin/users", handler.ListUsers)
	router.Patch("/v1/admin/users/{user_id}/status", handler.UpdateUserStatus)
	router.Get("/v1/admin/users/{user_id}/groups", handler.ListUserGroups)
	router.Put("/v1/admin/users/{user_id}/groups/{group_code}", handler.GrantUserGroup)
	router.Delete("/v1/admin/users/{user_id}/groups/{group_code}", handler.RevokeUserGroup)
	router.Get("/v1/admin/groups", handler.ListGroups)
	router.Post("/v1/admin/groups", handler.CreateGroup)
	router.Patch("/v1/admin/groups/{group_code}", handler.UpdateGroup)
	router.Delete("/v1/admin/groups/{group_code}", handler.DeleteGroup)
	router.Get("/v1/admin/groups/{group_code}/permissions", handler.ListGroupPermissions)
	router.Put("/v1/admin/groups/{group_code}/permissions/{permission_code}", handler.GrantGroupPermission)
	router.Delete("/v1/admin/groups/{group_code}/permissions/{permission_code}", handler.RevokeGroupPermission)
	router.Get("/v1/admin/permissions", handler.ListPermissions)
	router.Post("/v1/admin/permissions", handler.CreatePermission)
	router.Patch("/v1/admin/permissions/{permission_code}", handler.UpdatePermission)
	router.Delete("/v1/admin/permissions/{permission_code}", handler.DeletePermission)
	return router
}
