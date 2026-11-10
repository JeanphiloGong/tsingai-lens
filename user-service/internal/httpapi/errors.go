package httpapi

import (
	"errors"
	"fmt"
	"log/slog"
	"net/http"

	"github.com/JeanphiloGong/tsingai-lens/user-service/internal/domain"
	"github.com/JeanphiloGong/tsingai-lens/user-service/internal/service"
)

// writeError maps categories to HTTP status, without exposing diagnostic error text
func writeError(w http.ResponseWriter, err error) {
	err = service.ClassifyDependencyError(err)
	statusCode := http.StatusInternalServerError
	errorCode := "internal_error"

	var businessError *domain.Error

	if errors.As(err, &businessError) {
		switch businessError.Kind {
		case domain.Unauthenticated:
			statusCode = http.StatusUnauthorized
		case domain.Forbidden:
			statusCode = http.StatusForbidden
		case domain.InvalidInput:
			statusCode = http.StatusUnprocessableEntity
		case domain.Conflict:
			statusCode = http.StatusConflict
		case domain.Unavailable:
			statusCode = http.StatusServiceUnavailable
		}
		if statusCode != http.StatusInternalServerError {
			errorCode = businessError.Code
		}
	}

	if statusCode >= 500 {
		// Error text can contain database values and mail recipients; do not log it here
		slog.Error("user-service request failed", "error_type", fmt.Sprintf("%T", err))
	}
	respond(w, statusCode, ErrorResponse{Code: errorCode})
}
