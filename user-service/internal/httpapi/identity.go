package httpapi

import (
	"errors"
	"net/http"
	"time"

	"github.com/JeanphiloGong/tsingai-lens/user-service/internal/domain"
)

const CookieName = "lens_session"

type LoginRequest struct {
	Email    string `json:"email"`
	Password string `json:"password"`
}

func readSessionToken(r *http.Request) string {
	cookie, err := r.Cookie(CookieName)
	if err != nil {
		return ""
	}
	return cookie.Value
}

func (h *Handler) setCookie(w http.ResponseWriter, value string, maxAge int) {
	http.SetCookie(
		w,
		&http.Cookie{
			Name:     CookieName,
			Value:    value,
			Path:     "/",
			HttpOnly: true,
			Secure:   h.SecureCookie,
			SameSite: http.SameSiteLaxMode,
			MaxAge:   maxAge,
		},
	)
}

func (h *Handler) Login(w http.ResponseWriter, r *http.Request) {
	var input LoginRequest
	if !decode(w, r, &input) {
		return
	}
	user, sessionToken, err := h.Service.Login(r.Context(), input.Email, input.Password)
	if errors.Is(err, domain.ErrUnauthenticated) {
		respond(w, http.StatusUnauthorized, ErrorResponse{Code: "invalid_credentials"})
		return
	}

	if err != nil {
		writeError(w, err)
		return
	}
	h.setCookie(w, sessionToken, int((24 * time.Hour).Seconds()))
	respond(w, 200, UserResponse{
		UserID:      user.ID,
		Email:       user.Email,
		DisplayName: user.Name,
	})
}

func (h *Handler) Logout(w http.ResponseWriter, r *http.Request) {
	if err := h.Service.Logout(r.Context(), readSessionToken(r)); err != nil {
		writeError(w, err)
		return
	}
	h.setCookie(w, "", -1)
	respond(w, 200, OKResponse{OK: true})
}

func (h *Handler) CurrentUser(w http.ResponseWriter, r *http.Request) {
	user, err := h.Service.Resolve(r.Context(), readSessionToken(r))
	if err != nil {
		writeError(w, err)
		return
	}
	respond(w, 200, UserResponse{
		UserID:      user.ID,
		Email:       user.Email,
		DisplayName: user.Name,
	})
}
