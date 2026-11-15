package httpapi

import (
	"net/http"
)

type SendEmailCodeRequest struct {
	Email   string `json:"email"`
	Purpose string `json:"purpose"`
}

type EmailChallengeResponse struct {
	ChallengeID string `json:"challenge_id"`
	ExpiresIn   int    `json:"expires_in"`
	RetryAfter  int    `json:"retry_after"`
}

type RegisterRequest struct {
	ChallengeID      string `json:"challenge_id"`
	Email            string `json:"email"`
	VerificationCode string `json:"code"`
	Password         string `json:"password"`
	DisplayName      string `json:"display_name"`
}

type ResetPasswordRequest struct {
	ChallengeID      string `json:"challenge_id"`
	Email            string `json:"email"`
	VerificationCode string `json:"code"`
	Password         string `json:"password"`
}

// declares the handler method that coordinates the request
func (h *Handler) SendEmailCode(w http.ResponseWriter, r *http.Request) {
	var input SendEmailCodeRequest
	if !decode(w, r, &input) {
		return
	}
	challengeID, err := h.Service.IssueEmailChallenge(r.Context(), input.Email, input.Purpose, clientIP(r, h.TrustedProxy))
	if err != nil {
		writeError(w, err)
		return
	}
	respond(w, 202, EmailChallengeResponse{ChallengeID: challengeID, ExpiresIn: 600, RetryAfter: 60})
}

// declares the handler that handles one registration request
func (h *Handler) Register(w http.ResponseWriter, r *http.Request) {
	var input RegisterRequest
	if !decode(w, r, &input) {
		return
	}
	user, err := h.Service.CompleteEmailChallenge(r.Context(), input.ChallengeID, input.Email, "register", input.VerificationCode, input.Password, input.DisplayName, clientIP(r, h.TrustedProxy))
	if err != nil {
		writeError(w, err)
		return
	}
	respond(w, 201, UserResponse{
		UserID:      user.ID,
		Email:       user.Email,
		DisplayName: user.Name,
	})
}

func (h *Handler) ResetPassword(w http.ResponseWriter, r *http.Request) {
	var input ResetPasswordRequest
	if !decode(w, r, &input) {
		return
	}
	_, err := h.Service.CompleteEmailChallenge(r.Context(), input.ChallengeID, input.Email, "password_reset", input.VerificationCode, input.Password, "", clientIP(r, h.TrustedProxy))
	if err != nil {
		writeError(w, err)
		return
	}
	respond(w, 200, OKResponse{OK: true})
}
