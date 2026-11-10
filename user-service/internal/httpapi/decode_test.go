package httpapi

import (
	"context"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/JeanphiloGong/tsingai-lens/user-service/internal/service"
)

func TestDecodeSingleJSON(t *testing.T) {
	ctx := context.Background()
	pool := testPool(t)
	var err error
	account := &service.Service{Pool: pool}
	if err = account.Bootstrap(ctx, "review@example.test", "review-only-password"); err != nil {
		t.Fatal(err)
	}
	handler := Router(account, "http://review.test", false)
	login := `{"email":"review@example.test","password":"review-only-password"}`
	for _, item := range []struct {
		name, body string
		status     int
	}{
		{"second object", login + ` {"unexpected":true}`, 422},
		{"garbage", login + ` trailing`, 422},
		{"oversize", login + strings.Repeat(" ", 8192), 422},
		{"unknown field", `{"email":"review@example.test","password":"review-only-password","target":"other"}`, 422},
		{"trailing whitespace", login + " \n\t", 200},
	} {
		t.Run(item.name, func(t *testing.T) {
			if _, err = pool.Exec(ctx, "TRUNCATE sessions"); err != nil {
				t.Fatal(err)
			}
			request := httptest.NewRequest("POST", "/v1/login", strings.NewReader(item.body))
			request.Header.Set("Origin", "http://review.test")
			response := httptest.NewRecorder()
			handler.ServeHTTP(response, request)
			var count int
			if err = pool.QueryRow(ctx, "SELECT count(*) FROM sessions").Scan(&count); err != nil {
				t.Fatal(err)
			}
			expected := 0
			if item.status == 200 {
				expected = 1
			}
			if response.Code != item.status || count != expected || len(response.Result().Cookies()) != expected {
				t.Fatal(response.Code, count, response.Body.String())
			}
		})
	}
}
