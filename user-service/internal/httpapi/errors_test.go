package httpapi

import (
	"context"
	"errors"
	"fmt"
	"net"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/JeanphiloGong/tsingai-lens/user-service/internal/domain"
	"github.com/JeanphiloGong/tsingai-lens/user-service/internal/service"
	"github.com/jackc/pgx/v5/pgconn"
	"github.com/jackc/pgx/v5/pgxpool"
)

func TestErrorContract(t *testing.T) {
	cases := []struct {
		name   string
		err    error
		status int
		code   string
	}{
		{"wrapped authentication", fmt.Errorf("private context: %w", domain.ErrUnauthenticated), 401, "authentication_required"},
		{"wrapped forbidden", fmt.Errorf("private context: %w", service.ErrForbidden), 403, "permission_denied"},
		{"wrapped invalid", fmt.Errorf("private context: %w", service.ErrInvalid), 422, "invalid_request"},
		{"wrapped conflict", fmt.Errorf("private context: %w", service.ErrConflict), 409, "operation_conflict"},
		{"new conflict code", fmt.Errorf("private context: %w", &domain.Error{Kind: domain.Conflict, Code: "another_conflict"}), 409, "another_conflict"},
		{"unknown category", &domain.Error{Kind: domain.Kind("future"), Code: "must_not_leak"}, 500, "internal_error"},
		{"unexpected", errors.New("private credentials or diagnostic"), 500, "internal_error"},
		{"unknown unique constraint", &pgconn.PgError{Code: "23505", ConstraintName: "sessions_pkey", Detail: "private diagnostic"}, 500, "internal_error"},
		{"unknown foreign key", &pgconn.PgError{Code: "23503", ConstraintName: "internal_reference"}, 500, "internal_error"},
		{"unknown check constraint", &pgconn.PgError{Code: "23514"}, 500, "internal_error"},
		{"database stopping", &pgconn.PgError{Code: "57P01"}, 503, "identity_unavailable"},
	}
	for _, item := range cases {
		t.Run(item.name, func(t *testing.T) {
			response := httptest.NewRecorder()
			writeError(response, item.err)
			expected := `{"code":"` + item.code + `"}`
			if response.Code != item.status || strings.TrimSpace(response.Body.String()) != expected {
				t.Fatalf("status=%d body=%s", response.Code, response.Body.String())
			}
		})
	}
}

func TestDatabaseErrorResponses(t *testing.T) {
	ctx := context.Background()
	pool := testPool(t)
	var err error
	s := &service.Service{Pool: pool}
	if err = s.Bootstrap(ctx, "error-test@example.test", "tutorial-only-password"); err != nil {
		t.Fatal(err)
	}
	// An unexpected database failure during login must roll back session creation.
	_, err = pool.Exec(ctx, `CREATE FUNCTION tutorial_fail_session() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'private database detail'; END $$;
 CREATE TRIGGER tutorial_fail_session BEFORE INSERT ON sessions FOR EACH ROW EXECUTE FUNCTION tutorial_fail_session()`)
	if err != nil {
		t.Fatal(err)
	}
	defer pool.Exec(ctx, "DROP TRIGGER tutorial_fail_session ON sessions; DROP FUNCTION tutorial_fail_session()")
	request := httptest.NewRequest("POST", "/v1/login", strings.NewReader(`{"email":"error-test@example.test","password":"tutorial-only-password"}`))
	request.Header.Set("Origin", "http://localhost:5173")
	response := httptest.NewRecorder()
	Router(s, "http://localhost:5173", false).ServeHTTP(response, request)
	if response.Code != 500 || strings.TrimSpace(response.Body.String()) != `{"code":"internal_error"}` {
		t.Fatal(response.Code, response.Body.String())
	}
	var count int
	if err = pool.QueryRow(ctx, "SELECT count(*) FROM sessions").Scan(&count); err != nil || count != 0 {
		t.Fatal("failed login wrote sessions", count, err)
	}
	// A real refused TCP connection is a dependency outage, unlike a closed local pool.
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	address := listener.Addr().String()
	listener.Close()
	host, port, err := net.SplitHostPort(address)
	if err != nil {
		t.Fatal(err)
	}
	refused, err := pgxpool.New(ctx, "postgres://postgres@"+net.JoinHostPort(host, port)+"/unavailable?sslmode=disable&connect_timeout=1")
	if err != nil {
		t.Fatal(err)
	}
	defer refused.Close()
	unavailableService := &service.Service{Pool: refused}
	request = httptest.NewRequest("GET", "/v1/me", nil)
	request.Header.Set("Cookie", "lens_session=synthetic-token")
	response = httptest.NewRecorder()
	Router(unavailableService, "http://localhost:5173", false).ServeHTTP(response, request)
	if response.Code != 503 || strings.TrimSpace(response.Body.String()) != `{"code":"identity_unavailable"}` {
		t.Fatal(response.Code, response.Body.String())
	}
}
