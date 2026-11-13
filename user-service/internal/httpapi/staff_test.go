package httpapi

import (
	"context"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/JeanphiloGong/tsingai-lens/user-service/internal/service"
)

func TestStaffCheckpoint(t *testing.T) {
	ctx := context.Background()
	pool := testPool(t)
	var err error
	identity := &service.Service{Pool: pool}
	if err = identity.Bootstrap(ctx, "operator@example.test", "tutorial-only-password"); err != nil {
		t.Fatal(err)
	}
	if err = identity.InitializeAdmin(ctx, "operator@example.test"); err != nil {
		t.Fatal(err)
	}
	admin, adminToken, err := identity.Login(ctx, "operator@example.test", "tutorial-only-password")
	if err != nil {
		t.Fatal(err)
	}
	if _, err = pool.Exec(ctx, `INSERT INTO users(user_id,email,password_hash) SELECT 'staff','staff@example.test',password_hash FROM users WHERE user_id=$1`, admin.ID); err != nil {
		t.Fatal(err)
	}
	staff, staffToken, err := identity.Login(ctx, "staff@example.test", "tutorial-only-password")
	if err != nil {
		t.Fatal(err)
	}
	router := Router(identity, "http://localhost:5173", false)
	call := func(method, path, body string, status int) {
		request := httptest.NewRequest(method, path, strings.NewReader(body))
		request.Header.Set("Origin", "http://localhost:5173")
		request.AddCookie(&http.Cookie{Name: CookieName, Value: adminToken})
		response := httptest.NewRecorder()
		router.ServeHTTP(response, request)
		if response.Code != status {
			t.Fatalf("%s %s: %d %s", method, path, response.Code, response.Body)
		}
	}
	path := "/v1/admin/users/" + staff.ID
	for _, body := range []string{`{}`, `{"active":null}`} {
		call("PATCH", path+"/status", body, 422)
	}
	for attempt := 0; attempt < 2; attempt++ {
		call("PUT", path+"/groups/annotator", "", 200)
	}
	call("GET", path+"/groups", "", 200)
	allowed, err := identity.Check(ctx, staff.ID, "annotation.annotate")
	if err != nil || !allowed {
		t.Fatal(allowed, err)
	}
	for attempt := 0; attempt < 2; attempt++ {
		call("DELETE", path+"/groups/annotator", "", 200)
	}
	allowed, err = identity.Check(ctx, staff.ID, "annotation.annotate")
	if err != nil || allowed {
		t.Fatal(allowed, err)
	}
	call("PATCH", path+"/status", `{"active":false}`, 200)
	if _, err = identity.Resolve(ctx, staffToken); err == nil {
		t.Fatal("disabled session survived")
	}
	call("PATCH", "/v1/admin/users/"+admin.ID+"/status", `{"active":false}`, 409)
	call("DELETE", "/v1/admin/users/"+admin.ID+"/groups/admin", "", 409)
}
