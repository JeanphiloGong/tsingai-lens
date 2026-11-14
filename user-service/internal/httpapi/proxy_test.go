package httpapi

import (
	"context"
	"net"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/JeanphiloGong/tsingai-lens/user-service/internal/service"
	"github.com/jackc/pgx/v5/pgxpool"
)

func TestTrustedProxy(t *testing.T) {
	for _, test := range []struct {
		name, peer, trusted, header, want string
	}{
		{"direct", "10.0.0.11:1234", "", "203.0.113.1", "10.0.0.11"},
		{"unknown proxy", "10.0.0.11:1234", "10.0.0.10", "203.0.113.1", "10.0.0.11"},
		{"trusted proxy", "10.0.0.10:1234", "10.0.0.10", "203.0.113.1", "203.0.113.1"},
		{"invalid header", "10.0.0.10:1234", "10.0.0.10", "invalid", "10.0.0.10"},
		{"list is not an IP", "10.0.0.10:1234", "10.0.0.10", "203.0.113.1, 203.0.113.2", "10.0.0.10"},
		{"IPv6", "[::1]:1234", "::1", "2001:db8::1", "2001:db8::1"},
	} {
		t.Run(test.name, func(t *testing.T) {
			request := httptest.NewRequest("POST", "/v1/login", nil)
			request.RemoteAddr = test.peer
			request.Header.Set("X-Real-IP", test.header)
			if got := clientIP(request, test.trusted); got != test.want {
				t.Fatalf("got %q, want %q", got, test.want)
			}
		})
	}
}

func TestReadiness(t *testing.T) {
	pool := testPool(t)
	response := httptest.NewRecorder()
	Router(&service.Service{Pool: pool}, "https://lens.example.test", true, "").ServeHTTP(
		response, httptest.NewRequest("GET", "/ready", nil),
	)
	if response.Code != 200 || strings.TrimSpace(response.Body.String()) != `{"ok":true}` {
		t.Fatalf("unexpected readiness: %d %s", response.Code, response.Body.String())
	}
	if cookies := response.Result().Cookies(); len(cookies) != 0 {
		t.Fatal("readiness must not create a session")
	}
}

func TestReadinessUnavailable(t *testing.T) {
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	address := listener.Addr().String()
	listener.Close()
	pool, err := pgxpool.New(context.Background(), "postgres://postgres@"+address+"/unavailable?connect_timeout=1")
	if err != nil {
		t.Fatal(err)
	}
	defer pool.Close()
	response := httptest.NewRecorder()
	Router(&service.Service{Pool: pool}, "https://lens.example.test", true, "").ServeHTTP(
		response, httptest.NewRequest("GET", "/ready", nil),
	)
	if response.Code != 503 || strings.TrimSpace(response.Body.String()) != `{"code":"identity_unavailable"}` {
		t.Fatalf("unexpected readiness failure: %d %s", response.Code, response.Body.String())
	}
}
