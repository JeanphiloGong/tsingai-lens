package httpapi

import (
	"encoding/json"
	"errors"
	"github.com/JeanphiloGong/tsingai-lens/user-service/internal/service"
	"github.com/go-chi/chi/v5"
	"io"
	"net/http"
)

type OKResponse struct {
	OK bool `json:"ok"`
}

type ErrorResponse struct {
	Code string `json:"code"`
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
func Router(s *service.Service, origin string, secure bool) http.Handler {
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
	handler := &Handler{Service: s, SecureCookie: secure}
	router.Post("/v1/login", handler.Login)
	router.Post("/v1/logout", handler.Logout)
	router.Get("/v1/me", handler.CurrentUser)
	return router
}
