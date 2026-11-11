package httpapi

import (
	"context"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"

	"github.com/JeanphiloGong/tsingai-lens/user-service/internal/domain"
	"github.com/JeanphiloGong/tsingai-lens/user-service/internal/service"
)

func TestChangePassword(t *testing.T) {
	ctx := context.Background()
	pool := testPool(t)
	var err error
	userService := &service.Service{Pool: pool}
	password := "tutorial-only-password"
	if err = userService.Bootstrap(ctx, "owner@example.test", password); err != nil {
		t.Fatal(err)
	}
	if _, err = pool.Exec(ctx, "INSERT INTO users(user_id,email,password_hash) SELECT 'other','other@example.test',password_hash FROM users"); err != nil {
		t.Fatal(err)
	}
	_, firstToken, err := userService.Login(ctx, "owner@example.test", password)
	if err != nil {
		t.Fatal(err)
	}
	_, secondToken, err := userService.Login(ctx, "owner@example.test", password)
	if err != nil {
		t.Fatal(err)
	}
	_, otherToken, err := userService.Login(ctx, "other@example.test", password)
	if err != nil {
		t.Fatal(err)
	}
	handler := Router(userService, "http://localhost:5173", false)
	call := func(body string) *httptest.ResponseRecorder {
		request := httptest.NewRequest("POST", "/v1/me/password", strings.NewReader(body))
		request.Header.Set("Origin", "http://localhost:5173")
		request.AddCookie(&http.Cookie{Name: CookieName, Value: firstToken})
		response := httptest.NewRecorder()
		handler.ServeHTTP(response, request)
		return response
	}
	for _, body := range []string{
		`{"old_password":"tutorial-only-password","password":"changed-tutorial-password","target":"other"}`,
		`{"old_password":"tutorial-only-password","password":"changed-tutorial-password","action":"grant"}`,
		`{"old_password":"tutorial-only-password","password":"short"}`,
	} {
		response := call(body)
		if response.Code != 422 || response.Header().Get("Set-Cookie") != "" {
			t.Fatal(response.Code, response.Body)
		}
	}
	wrong := call(`{"old_password":"wrong","password":"changed-tutorial-password"}`)
	if wrong.Code != 401 || strings.TrimSpace(wrong.Body.String()) != `{"code":"authentication_required"}` {
		t.Fatal(wrong.Code, wrong.Body)
	}
	if _, err = userService.Resolve(ctx, firstToken); err != nil {
		t.Fatal("rejected request revoked session", err)
	}
	changed := call(`{"old_password":"tutorial-only-password","password":"changed-tutorial-password"}`)
	if changed.Code != 200 || strings.TrimSpace(changed.Body.String()) != `{"ok":true}` || !strings.Contains(changed.Header().Get("Set-Cookie"), "Max-Age=0") {
		t.Fatal(changed.Code, changed.Body, changed.Header())
	}
	for _, sessionToken := range []string{firstToken, secondToken} {
		if _, err = userService.Resolve(ctx, sessionToken); err != domain.ErrUnauthenticated {
			t.Fatal("old session survived", err)
		}
	}
	if _, _, err = userService.Login(ctx, "owner@example.test", password); err != domain.ErrUnauthenticated {
		t.Fatal("old password accepted", err)
	}
	_, freshToken, err := userService.Login(ctx, "owner@example.test", "changed-tutorial-password")
	if err != nil {
		t.Fatal(err)
	}
	if _, err = userService.Resolve(ctx, otherToken); err != nil {
		t.Fatal("another account changed", err)
	}
	// Two callers with the same old session cannot both overwrite the password.
	results := make(chan error, 2)
	var callers sync.WaitGroup
	for range 2 {
		callers.Add(1)
		go func() {
			defer callers.Done()
			results <- userService.ChangePassword(ctx, freshToken, "changed-tutorial-password", "second-tutorial-password")
		}()
	}
	callers.Wait()
	close(results)
	success := 0
	for result := range results {
		if result == nil {
			success++
		} else if result != domain.ErrUnauthenticated {
			t.Fatal(result)
		}
	}
	if success != 1 {
		t.Fatal("concurrent password changes", success)
	}
	pool.Close()
	unavailable := call(`{"old_password":"second-tutorial-password","password":"third-tutorial-password"}`)
	if unavailable.Code != 500 || strings.TrimSpace(unavailable.Body.String()) != `{"code":"internal_error"}` {
		t.Fatal(unavailable.Code, unavailable.Body)
	}
}
