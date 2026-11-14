package httpapi

import (
	"net/http"

	"github.com/JeanphiloGong/tsingai-lens/user-service/internal/service"
)

type Handler struct {
	Service      *service.Service
	SecureCookie bool
	TrustedProxy string
}

func (h *Handler) Ready(w http.ResponseWriter, r *http.Request) {
	if err := h.Service.Pool.Ping(r.Context()); err != nil {
		writeError(w, err)
		return
	}
	respond(w, http.StatusOK, OKResponse{OK: true})
}
