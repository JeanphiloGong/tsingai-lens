package httpapi

import (
	"errors"
	"net/http"
	"time"

	"github.com/JeanphiloGong/tsingai-lens/user-service/internal/domain"
)

const CookieName = "lens_session"

// LoginRequest contains the credentials submitted during login
type LoginRequest struct {
	Email    string `json:"email"`
	Password string `json:"password"`
}

// ChangePasswordRequest contains the current and replacement passwords.
type ChangePasswordRequest struct {
	OldPassword string `json:"old_password"`
	Password    string `json:"password"`
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

// declares a method of Handler that gets the current user's info
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

// ChangePassword updates the authenticated user's password and clears its cookie.
func (h *Handler) ChangePassword(w http.ResponseWriter, r *http.Request) {
	var input ChangePasswordRequest
	if !decode(w, r, &input) {
		return
	}
	if err := h.Service.ChangePassword(
		r.Context(),
		readSessionToken(r),
		input.OldPassword,
		input.Password,
	); err != nil {
		writeError(w, err)
		return
	}
	h.setCookie(w, "", -1)
	respond(w, http.StatusOK, OKResponse{OK: true})
}
