package httpapi

import (
	"context"
	"fmt"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/JeanphiloGong/tsingai-lens/user-service/internal/service"
)

func TestLoginLimitIndependentOfRegistration(t *testing.T) {
	ctx := context.Background()
	pool := testPool(t)
	var err error
	for _, enabled := range []bool{true, false} {
		name := "closed_registration"
		if enabled {
			name = "open_registration"
		}
		t.Run(name, func(t *testing.T) {
			if _, err = pool.Exec(ctx, "TRUNCATE users,auth_rate_limits CASCADE"); err != nil {
				t.Fatal(err)
			}
			account := &service.Service{Pool: pool, RegistrationEnabled: enabled}
			if err = account.Bootstrap(ctx, "rate-review@example.test", "review-only-password"); err != nil {
				t.Fatal(err)
			}
			handler := Router(account, "http://review.test", false, "")
			for attempt := 0; attempt < 11; attempt++ {
				request := httptest.NewRequest("POST", "/v1/login", strings.NewReader(`{"email":"rate-review@example.test","password":"wrong-password"}`))
				request.Header.Set("Origin", "http://review.test")
				request.RemoteAddr = "127.0.0.1:12345"
				request.Header.Set("X-Real-IP", fmt.Sprintf("192.0.2.%d", attempt+1))
				response := httptest.NewRecorder()
				handler.ServeHTTP(response, request)
				expected := 401
				if attempt == 10 {
					expected = 429
				}
				if response.Code != expected {
					t.Fatalf("attempt%d: expected%d got%d", attempt+1, expected, response.Code)
				}
				if expected == 429 && response.Header().Get("Retry-After") == "" {
					t.Fatal("missing retry metadata")
				}
			}
			var count int
			if err = pool.QueryRow(ctx, "SELECT count(*) FROM sessions").Scan(&count); err != nil || count != 0 {
				t.Fatal(count, err)
			}
		})
	}
}

func TestLoginLimitsCountSuccessfulAndFailedAttempts(t *testing.T) {
	pool := testPool(t)
	account := &service.Service{Pool: pool}
	const email = "login-count@example.test"
	const password = "tutorial-only-password"
	if err := account.Bootstrap(t.Context(), email, password); err != nil {
		t.Fatal(err)
	}
	for index, input := range []struct {
		password string
		status   int
	}{{password, 200}, {"wrong-password", 401}, {password, 200}} {
		// A new handler/service instance must reuse committed database counters.
		handler := Router(&service.Service{Pool: pool}, "http://review.test", false, "")
		body := fmt.Sprintf(`{"email":%q,"password":%q}`, email, input.password)
		request := httptest.NewRequest("POST", "/v1/login", strings.NewReader(body))
		request.Header.Set("Origin", "http://review.test")
		request.RemoteAddr = "127.0.0.1:12345"
		response := httptest.NewRecorder()
		handler.ServeHTTP(response, request)
		if response.Code != input.status {
			t.Fatal(response.Code, response.Body)
		}
		for _, key := range []string{"login-email:" + email, "login-ip:127.0.0.1"} {
			var used int
			if err := pool.QueryRow(t.Context(), "SELECT used FROM auth_rate_limits WHERE key=$1", key).Scan(&used); err != nil || used != index+1 {
				t.Fatal("login attempt count", key, used, err)
			}
		}
	}
}
