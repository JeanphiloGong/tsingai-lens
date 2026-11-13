package httpapi

import (
	"context"
	"encoding/json"
	"github.com/jackc/pgx/v5/pgxpool"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"testing"

	"github.com/JeanphiloGong/tsingai-lens/user-service/internal/service"
)

// Run only against the disposable database created by the tutorial.
func TestLoginLifecycle(t *testing.T) {
	ctx := context.Background()
	pool := testPool(t)
	var err error
	s := &service.Service{Pool: pool}
	password := "tutorial-only-password"
	if err = s.Bootstrap(ctx, "owner@example.test", password); err != nil {
		t.Fatal(err)
	}
	if err = s.Bootstrap(ctx, "other@example.test", password); err != service.ErrConflict {
		t.Fatalf("second bootstrap: %v", err)
	}
	handler := Router(s, "http://localhost:5173", false)
	call := func(method, path, body, cookie string) *httptest.ResponseRecorder {
		r := httptest.NewRequest(method, path, strings.NewReader(body))
		r.Header.Set("Origin", "http://localhost:5173")
		r.Header.Set("Cookie", cookie)
		w := httptest.NewRecorder()
		handler.ServeHTTP(w, r)
		return w
	}
	bad := call("POST", "/v1/login", `{"email":"owner@example.test","password":"wrong"}`, "")
	if bad.Code != 401 || strings.TrimSpace(bad.Body.String()) != `{"code":"invalid_credentials"}` || len(bad.Result().Cookies()) != 0 {
		t.Fatal(bad.Code, bad.Body.String())
	}
	login := call("POST", "/v1/login", `{"email":"owner@example.test","password":"tutorial-only-password"}`, "")
	if login.Code != 200 {
		t.Fatal(login.Code, login.Body.String())
	}
	var publicUser map[string]any
	if err := json.Unmarshal(login.Body.Bytes(), &publicUser); err != nil {
		t.Fatal(err)
	}
	userID, hasUserID := publicUser["user_id"].(string)
	if len(publicUser) != 3 || publicUser["email"] != "owner@example.test" || publicUser["display_name"] != "Administrator" || !hasUserID || userID == "" {
		t.Fatal("unexpected public user response", publicUser)
	}
	if login.Header().Get("Cache-Control") != "no-store" || login.Header().Get("Content-Type") != "application/json" {
		t.Fatal("login response must be JSON and must not be cached")
	}
	cookie := login.Result().Cookies()[0]
	if cookie.Name != CookieName || cookie.Path != "/" || !cookie.HttpOnly || cookie.SameSite != http.SameSiteLaxMode || cookie.MaxAge != 86400 || cookie.Secure {
		t.Fatal("cookie contract", cookie)
	}
	cookieHeader := cookie.Name + "=" + cookie.Value
	if call("GET", "/v1/me", "", cookieHeader).Code != 200 {
		t.Fatal("session not readable")
	}
	for i := 0; i < 2; i++ {
		logout := call("POST", "/v1/logout", "", cookieHeader)
		if logout.Code != 200 {
			t.Fatal("logout not idempotent")
		}
		deleted := logout.Result().Cookies()[0]
		if deleted.Name != CookieName || deleted.Path != "/" || deleted.MaxAge >= 0 {
			t.Fatal("logout must delete the same cookie")
		}
	}
	if call("GET", "/v1/me", "", cookieHeader).Code != 401 {
		t.Fatal("revoked session allowed")
	}
	_, sessionToken, err := s.Login(ctx, "owner@example.test", password)
	if err != nil {
		t.Fatal(err)
	}
	if _, err = pool.Exec(ctx, "UPDATE sessions SET expires_at=now()-interval '1 second'"); err != nil {
		t.Fatal(err)
	}
	if call("GET", "/v1/me", "", CookieName+"="+sessionToken).Code != 401 {
		t.Fatal("expired session allowed")
	}
	_, sessionToken, err = s.Login(ctx, "owner@example.test", password)
	if err != nil {
		t.Fatal(err)
	}
	if _, err = pool.Exec(ctx, "UPDATE users SET active=false"); err != nil {
		t.Fatal(err)
	}
	if call("GET", "/v1/me", "", CookieName+"="+sessionToken).Code != 401 {
		t.Fatal("disabled user allowed")
	}
	if call("POST", "/v1/login", `{"email":"owner@example.test","password":"tutorial-only-password"}`, "").Code != 401 {
		t.Fatal("disabled account logged in with a matching password")
	}
}

func TestOriginAndSessionBoundaries(t *testing.T) {
	pool := testPool(t)
	account := &service.Service{Pool: pool}
	if err := account.Bootstrap(context.Background(), "owner@example.test", "tutorial-only-password"); err != nil {
		t.Fatal(err)
	}
	handler := Router(account, "https://lens.example.test", true)
	login := `{"email":"owner@example.test","password":"tutorial-only-password"}`
	for _, origin := range []string{"", "https://untrusted.example.test"} {
		request := httptest.NewRequest("POST", "/v1/login", strings.NewReader(login))
		request.Header.Set("Origin", origin)
		response := httptest.NewRecorder()
		handler.ServeHTTP(response, request)
		if response.Code != 403 || len(response.Result().Cookies()) != 0 {
			t.Fatal("untrusted write accepted", response.Code)
		}
	}
	var count int
	if err := pool.QueryRow(context.Background(), "SELECT count(*) FROM sessions").Scan(&count); err != nil || count != 0 {
		t.Fatal("rejected writes created sessions", count, err)
	}
	for _, token := range []string{"", "forged-token"} {
		request := httptest.NewRequest("GET", "/v1/me", nil)
		request.AddCookie(&http.Cookie{Name: CookieName, Value: token})
		response := httptest.NewRecorder()
		handler.ServeHTTP(response, request)
		if response.Code != 401 {
			t.Fatal("invalid session accepted", response.Code)
		}
	}
	request := httptest.NewRequest("POST", "/v1/login", strings.NewReader(login))
	request.Header.Set("Origin", "https://lens.example.test")
	response := httptest.NewRecorder()
	handler.ServeHTTP(response, request)
	if response.Code != 200 || !response.Result().Cookies()[0].Secure {
		t.Fatal("secure-cookie configuration was not applied", response.Code)
	}
}

func testPool(t *testing.T) *pgxpool.Pool {
	t.Helper()
	databaseURL := os.Getenv("TEST_USER_DATABASE_URL")
	if databaseURL == "" {
		t.Skip("set TEST_USER_DATABASE_URL to a disposable migrated *_test database")
	}
	config, err := pgxpool.ParseConfig(databaseURL)
	if err != nil {
		t.Fatal("invalid TEST_USER_DATABASE_URL")
	}
	// These integration tests clear account data; never accept an ordinary database.
	if !strings.HasSuffix(config.ConnConfig.Database, "_test") {
		t.Fatal("TEST_USER_DATABASE_URL must name a disposable *_test database")
	}
	pool, err := pgxpool.NewWithConfig(context.Background(), config)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(pool.Close)
	if _, err := pool.Exec(context.Background(), "TRUNCATE users CASCADE; TRUNCATE auth_audit, email_challenges, auth_rate_limits"); err != nil {
		t.Fatal(err)
	}
	return pool
}
