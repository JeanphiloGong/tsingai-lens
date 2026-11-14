package httpapi

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/JeanphiloGong/tsingai-lens/user-service/internal/service"
)

// This synthetic fixture is confined to TEST_USER_DATABASE_URL.
func TestCatalogReadCheckpoint(t *testing.T) {
	ctx := context.Background()
	pool := testPool(t)
	var err error
	identity := &service.Service{Pool: pool}
	if err = identity.Bootstrap(ctx, "reader@example.test", "tutorial-only-password"); err != nil {
		t.Fatal(err)
	}
	_, token, err := identity.Login(ctx, "reader@example.test", "tutorial-only-password")
	if err != nil {
		t.Fatal(err)
	}
	router := Router(identity, "http://localhost:5173", false, "")
	get := func(path string) *httptest.ResponseRecorder {
		request := httptest.NewRequest("GET", path, nil)
		request.AddCookie(&http.Cookie{Name: CookieName, Value: token})
		response := httptest.NewRecorder()
		router.ServeHTTP(response, request)
		return response
	}
	if response := get("/v1/me/permissions"); response.Code != 200 || strings.TrimSpace(response.Body.String()) != `{"permission_codes":[]}` {
		t.Fatal(response.Code, response.Body)
	}
	if response := get("/v1/admin/groups"); response.Code != 403 {
		t.Fatal(response.Code, response.Body)
	}
	if err = identity.InitializeAdmin(ctx, "reader@example.test"); err != nil {
		t.Fatal(err)
	}
	for _, path := range []string{"/v1/admin/users", "/v1/admin/groups", "/v1/admin/permissions"} {
		response := get(path + "?limit=1&offset=0")
		var page struct {
			Items  []json.RawMessage `json:"items"`
			Total  int
			Limit  int
			Offset int
		}
		if response.Code != 200 || json.Unmarshal(response.Body.Bytes(), &page) != nil || page.Total < 1 || len(page.Items) != 1 || page.Limit != 1 {
			t.Fatal(path, response.Code, response.Body)
		}
	}
	response := get("/v1/admin/groups?limit=0")
	if response.Code != 422 {
		t.Fatal(response.Code, response.Body)
	}
	if response = get("/v1/me/permissions"); !strings.Contains(response.Body.String(), "users.manage") {
		t.Fatal(response.Body)
	}
}
