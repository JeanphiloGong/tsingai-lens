package domain

import (
	"errors"
	"fmt"
	"testing"
)

func TestErrorCategories(t *testing.T) {
	for _, code := range []string{"operation_conflict", "already_exists"} {
		failure := &Error{Kind: Conflict, Code: code}
		cause := errors.New("private diagnostic")
		wrapped := fmt.Errorf("account operation: %w: %w", failure, cause)
		var businessError *Error
		if !errors.Is(wrapped, Conflict) || !errors.Is(wrapped, failure) || !errors.Is(wrapped, cause) || !errors.As(wrapped, &businessError) || businessError.Code != code {
			t.Fatal("category, concrete identity, diagnostic cause and public code must survive wrapping")
		}
	}
}
