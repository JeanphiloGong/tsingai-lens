package httpapi

import (
	"errors"
	"fmt"
	"log/slog"
	"net/http"
	"strconv"

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
		case domain.RateLimit:
			statusCode = http.StatusTooManyRequests
		}
		if statusCode != http.StatusInternalServerError {
			errorCode = businessError.Code
		}
	}

	// detects the rate-limit response path selected above
	if statusCode == http.StatusTooManyRequests {
		// declares `rate` as a pointer to `service.RateLimited`, initially `nil`
		var rate *service.RateLimited

		if errors.As(err, &rate) {
			// adds the HTTP `Retry-After` response header, telling the client how many seconds it should wait before retrying
			w.Header().Set("Retry-After", strconv.Itoa(rate.Seconds))
			respond(w, statusCode, ErrorResponse{
				Code:       errorCode,
				RetryAfter: rate.Seconds,
			})
			return
		}
	}

	if statusCode >= 500 {
		// Error text can contain database values and mail recipients; do not log it here
		slog.Error("user-service request failed", "error_type", fmt.Sprintf("%T", err))
	}
	respond(w, statusCode, ErrorResponse{Code: errorCode})
}
