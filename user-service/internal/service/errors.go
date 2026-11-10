package service

import (
	"errors"
	"fmt"
	"io"
	"net"
	"strings"

	"github.com/JeanphiloGong/tsingai-lens/user-service/internal/domain"
	"github.com/jackc/pgx/v5/pgconn"
)

var (
	ErrForbidden   = &domain.Error{Kind: domain.Forbidden, Code: "permission_denied"}
	ErrInvalid     = &domain.Error{Kind: domain.InvalidInput, Code: "invalid_request"}
	ErrConflict    = &domain.Error{Kind: domain.Conflict, Code: "operation_conflict"}
	errUnavailable = &domain.Error{Kind: domain.Unavailable, Code: "identity_unavailable"}
)

// ClassifyDependencyError preserves recognized business errors and their original causes
// It classifies dependency failures; it never retries the operation.
func ClassifyDependencyError(err error) error {
	var businessError *domain.Error
	if errors.As(err, &businessError) {
		return err
	}

	var networkError net.Error
	if errors.As(err, &networkError) || errors.Is(err, io.EOF) || errors.Is(err, io.ErrUnexpectedEOF) {
		return fmt.Errorf("%w: %w", errUnavailable, err)
	}
	var databaseError *pgconn.PgError
	if errors.As(err, &databaseError) && (strings.HasPrefix(databaseError.Code, "08") || databaseError.Code == "57P01" || databaseError.Code == "57P02" || databaseError.Code == "57P03") {
		return fmt.Errorf("%w: %w", errUnavailable, err)
	}
	return err
}
