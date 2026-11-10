package httpapi

import "github.com/JeanphiloGong/tsingai-lens/user-service/internal/service"

type Handler struct {
	Service      *service.Service
	SecureCookie bool
}
