package httpapi

import (
	"context"
	"encoding/json"
	"errors"
	"github.com/JeanphiloGong/tsingai-lens/user-service/internal/domain"
	"github.com/JeanphiloGong/tsingai-lens/user-service/internal/service"
	"github.com/jackc/pgx/v5/pgxpool"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"
)

type managementFixture struct {
	service                                *service.Service
	pool                                   *pgxpool.Pool
	handler                                http.Handler
	adminID, adminToken, userID, userToken string
}

func newManagementFixture(t *testing.T) *managementFixture {
	t.Helper()
	ctx := context.Background()
	pool := testPool(t)
	var err error
	// Catalog data is shared only inside this disposable test database.
	reset := `TRUNCATE users CASCADE;
 DELETE FROM group_permissions;
 DELETE FROM groups WHERE NOT is_system;
 DELETE FROM permissions WHERE NOT is_system;
 INSERT INTO group_permissions VALUES
 ('admin','users.manage'),('annotator','research.read_all'),('annotator','annotation.annotate'),
 ('reviewer','research.read_all'),('reviewer','annotation.review'),
 ('publisher','research.read_all'),('publisher','dataset.publish'),('publisher','dataset.download');`
	if _, err = pool.Exec(ctx, reset); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		if _, err := pool.Exec(ctx, reset); err != nil {
			t.Error(err)
		}
	})
	users := &service.Service{Pool: pool}
	if err = users.Bootstrap(ctx, "admin@example.test", "tutorial-only-password"); err != nil {
		t.Fatal(err)
	}
	if err = users.InitializeAdmin(ctx, "admin@example.test"); err != nil {
		t.Fatal(err)
	}
	admin, adminToken, err := users.Login(ctx, "admin@example.test", "tutorial-only-password")
	if err != nil {
		t.Fatal(err)
	}
	// Synthetic fixture only: the public system creates ordinary users through registration.
	if _, err = pool.Exec(ctx, `INSERT INTO users(user_id,email,password_hash,email_verified_at)
 SELECT 'ordinary','ordinary@example.test',password_hash,now() FROM users WHERE user_id=$1`, admin.ID); err != nil {
		t.Fatal(err)
	}
	user, userToken, err := users.Login(ctx, "ordinary@example.test", "tutorial-only-password")
	if err != nil {
		t.Fatal(err)
	}
	return &managementFixture{users, pool, Router(users, "http://localhost:5173", false, ""), admin.ID, adminToken, user.ID, userToken}
}
func (f *managementFixture) call(method, path, body, token string) *httptest.ResponseRecorder {
	request := httptest.NewRequest(method, path, strings.NewReader(body))
	request.Header.Set("Origin", "http://localhost:5173")
	request.AddCookie(&http.Cookie{Name: CookieName, Value: token})
	response := httptest.NewRecorder()
	f.handler.ServeHTTP(response, request)
	return response
}
func expectManagement(t *testing.T, f *managementFixture, method, path, body string, status int) *httptest.ResponseRecorder {
	t.Helper()
	response := f.call(method, path, body, f.adminToken)
	if response.Code != status {
		t.Fatalf("%s %s: %d %s", method, path, response.Code, response.Body)
	}
	return response
}
func TestManagementContract(t *testing.T) {
	f := newManagementFixture(t)
	ctx := context.Background()
	if got := f.call("GET", "/v1/admin/groups/missing/permissions", "", f.userToken); got.Code != 403 {
		t.Fatal("directory target disclosed", got.Code)
	}
	if got := f.call("GET", "/v1/me/permissions", "", f.userToken); strings.TrimSpace(got.Body.String()) != `{"permission_codes":[]}` {
		t.Fatal(got.Body)
	}
	for _, path := range []string{"/v1/admin/users", "/v1/admin/groups", "/v1/admin/permissions"} {
		response := expectManagement(t, f, "GET", path+"?limit=1&offset=1", "", 200)
		var page struct {
			Items         []json.RawMessage `json:"items"`
			Total         int               `json:"total"`
			Limit, Offset int
		}
		if json.Unmarshal(response.Body.Bytes(), &page) != nil || len(page.Items) != 1 || page.Limit != 1 || page.Offset != 1 {
			t.Fatal(response.Body)
		}
		var fields map[string]json.RawMessage
		json.Unmarshal(response.Body.Bytes(), &fields)
		if len(fields) != 4 || fields["users"] != nil {
			t.Fatal("old snapshot leaked", fields)
		}
	}
	for _, query := range []string{"limit=0", "limit=201", "offset=-1", "limit=oops", "offset="} {
		expectManagement(t, f, "GET", "/v1/admin/users?"+query, "", 422)
	}
	userPath := "/v1/admin/users/" + f.userID
	for _, body := range []string{`{}`, `{"active":null}`, `{"active":false,"password":"another-password"}`} {
		expectManagement(t, f, "PATCH", userPath+"/status", body, 422)
		if _, err := f.service.Resolve(ctx, f.userToken); err != nil {
			t.Fatal("invalid input revoked session", err)
		}
	}
	expectManagement(t, f, "GET", userPath+"/groups", "", 200)
	expectManagement(t, f, "GET", "/v1/admin/users/missing/groups", "", 422)
	expectManagement(t, f, "POST", "/v1/admin/groups", `{"code":"curators","name":" Curators ","description":"Synthetic catalog"}`, 201)
	expectManagement(t, f, "POST", "/v1/admin/groups", `{"code":"curators","name":"Duplicate"}`, 409)
	expectManagement(t, f, "POST", "/v1/admin/permissions", `{"code":"project.read","name":"Read projects"}`, 201)
	expectManagement(t, f, "POST", "/v1/admin/permissions", `{"code":"invalid","name":"Bad"}`, 422)
	expectManagement(t, f, "POST", "/v1/admin/groups", `{"code":"bad","name":"Bad","is_system":true}`, 422)
	for _, base := range []string{"/v1/admin/groups/curators", "/v1/admin/permissions/project.read"} {
		for _, body := range []string{`{}`, `{"name":null}`, `{"description":null}`, `{"code":"renamed"}`, `{"name":"  "}`} {
			expectManagement(t, f, "PATCH", base, body, 422)
		}
		expectManagement(t, f, "PATCH", base, `{"name":"Updated","description":""}`, 200)
	}
	expectManagement(t, f, "PATCH", "/v1/admin/groups/admin", `{"description":"Editable metadata"}`, 200)
	for n := 0; n < 2; n++ {
		expectManagement(t, f, "PUT", "/v1/admin/groups/curators/permissions/project.read", "", 200)
		expectManagement(t, f, "PUT", userPath+"/groups/curators", "", 200)
	}
	allowed, err := f.service.Check(ctx, f.userID, "project.read")
	if err != nil || !allowed {
		t.Fatal("grant not effective", allowed, err)
	}
	expectManagement(t, f, "DELETE", "/v1/admin/groups/admin", "", 403)
	expectManagement(t, f, "DELETE", "/v1/admin/permissions/users.manage", "", 403)
	expectManagement(t, f, "DELETE", "/v1/admin/groups/curators", "", 409)
	expectManagement(t, f, "DELETE", "/v1/admin/permissions/project.read", "", 409)
	expectManagement(t, f, "DELETE", "/v1/admin/groups/admin/permissions/users.manage", "", 409)
	expectManagement(t, f, "PATCH", "/v1/admin/users/"+f.adminID+"/status", `{"active":false}`, 409)
	expectManagement(t, f, "DELETE", "/v1/admin/users/"+f.adminID+"/groups/admin", "", 409)
	expectManagement(t, f, "PUT", userPath+"/groups/missing", "", 422)
	expectManagement(t, f, "DELETE", userPath+"/groups/missing", "", 422)
	expectManagement(t, f, "PUT", "/v1/admin/groups/curators/permissions/missing.code", "", 422)
	for n := 0; n < 2; n++ {
		expectManagement(t, f, "DELETE", userPath+"/groups/curators", "", 200)
	}
	allowed, err = f.service.Check(ctx, f.userID, "project.read")
	if err != nil || allowed {
		t.Fatal("revocation cached", allowed, err)
	}
	expectManagement(t, f, "DELETE", "/v1/admin/groups/curators", "", 200)
	expectManagement(t, f, "DELETE", "/v1/admin/permissions/project.read", "", 200)
	response := expectManagement(t, f, "PATCH", userPath+"/status", `{"active":false}`, 200)
	if !strings.Contains(response.Body.String(), `"active":false`) {
		t.Fatal(response.Body)
	}
	if _, err = f.service.Resolve(ctx, f.userToken); err == nil {
		t.Fatal("disabled session accepted")
	}
	expectManagement(t, f, "PATCH", userPath+"/status", `{"active":true}`, 200)
	if _, err = f.service.Resolve(ctx, f.userToken); err == nil {
		t.Fatal("re-enable restored session")
	}
	if got := f.call("POST", "/v1/admin/commands", `{"action":"create"}`, f.adminToken); got.Code == 200 {
		t.Fatal("retired command accepted")
	}
	var count int
	if err = f.pool.QueryRow(ctx, `SELECT count(*) FROM auth_audit WHERE target_type='group' AND action='group.permission.grant' AND details->>'permission_code'='project.read'`).Scan(&count); err != nil || count < 1 {
		t.Fatal("missing typed audit", count, err)
	}
}
func TestManagementRollbackAndConcurrency(t *testing.T) {
	f := newManagementFixture(t)
	ctx := context.Background()
	_, err := f.pool.Exec(ctx, `CREATE FUNCTION reject_management_audit() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'synthetic audit failure'; END $$;
 CREATE TRIGGER reject_management_audit BEFORE INSERT ON auth_audit FOR EACH ROW EXECUTE FUNCTION reject_management_audit();`)
	if err != nil {
		t.Fatal(err)
	}
	defer f.pool.Exec(ctx, `DROP TRIGGER IF EXISTS reject_management_audit ON auth_audit;DROP FUNCTION IF EXISTS reject_management_audit();`)
	expectManagement(t, f, "PATCH", "/v1/admin/users/"+f.userID+"/status", `{"active":false}`, 500)
	if _, err = f.service.Resolve(ctx, f.userToken); err != nil {
		t.Fatal("audit failure leaked session revocation", err)
	}
	expectManagement(t, f, "POST", "/v1/admin/groups", `{"code":"rolled_back","name":"Rollback"}`, 500)
	var count int
	if err := f.pool.QueryRow(ctx, `SELECT count(*) FROM groups WHERE code='rolled_back'`).Scan(&count); err != nil || count != 0 {
		t.Fatal("audit failure left group", count, err)
	}
	if _, err = f.pool.Exec(ctx, `DROP TRIGGER reject_management_audit ON auth_audit;DROP FUNCTION reject_management_audit();`); err != nil {
		t.Fatal(err)
	}
	expectManagement(t, f, "POST", "/v1/admin/groups", `{"code":"operators","name":"Operators"}`, 201)
	expectManagement(t, f, "PUT", "/v1/admin/groups/operators/permissions/users.manage", "", 200)
	expectManagement(t, f, "PUT", "/v1/admin/users/"+f.adminID+"/groups/operators", "", 200)
	expectManagement(t, f, "PUT", "/v1/admin/users/"+f.userID+"/groups/operators", "", 200)
	expectManagement(t, f, "DELETE", "/v1/admin/users/"+f.adminID+"/groups/admin", "", 200)
	var wg sync.WaitGroup
	statuses := make(chan int, 2)
	for _, person := range []struct{ id, token string }{{f.adminID, f.adminToken}, {f.userID, f.userToken}} {
		wg.Add(1)
		go func(id, token string) {
			defer wg.Done()
			statuses <- f.call("DELETE", "/v1/admin/users/"+id+"/groups/operators", "", token).Code
		}(person.id, person.token)
	}
	wg.Wait()
	close(statuses)
	successes, conflicts := 0, 0
	for status := range statuses {
		if status == 200 {
			successes++
		}
		if status == 409 {
			conflicts++
		}
	}
	if successes != 1 || conflicts != 1 {
		t.Fatal("last administrator race", successes, conflicts)
	}
	if err = f.pool.QueryRow(ctx, `SELECT count(DISTINCT u.user_id) FROM users u JOIN user_groups g USING(user_id) JOIN group_permissions p USING(group_code) WHERE u.active AND p.permission_code='users.manage'`).Scan(&count); err != nil || count != 1 {
		t.Fatal("effective admin invariant", count, err)
	}
}

func TestManagementRechecksSessionAfterPasswordChange(t *testing.T) {
	f := newManagementFixture(t)
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	blocker, err := f.pool.Begin(ctx)
	if err != nil {
		t.Fatal(err)
	}
	defer blocker.Rollback(ctx)
	if _, err := blocker.Exec(ctx, "SELECT user_id FROM users WHERE user_id=$1 FOR UPDATE", f.adminID); err != nil {
		t.Fatal(err)
	}
	waitForBlocked := func(count int) {
		t.Helper()
		for {
			var waiting int
			if err := f.pool.QueryRow(ctx, `SELECT count(*) FROM pg_stat_activity
WHERE datname=current_database() AND wait_event_type='Lock' AND query LIKE '%FOR UPDATE%'`).Scan(&waiting); err != nil {
				t.Fatal(err)
			}
			if waiting >= count {
				return
			}
			select {
			case <-ctx.Done():
				t.Fatal("operations did not reach the account lock", ctx.Err())
			case <-time.After(10 * time.Millisecond):
			}
		}
	}
	changed := make(chan error, 1)
	go func() {
		changed <- f.service.ChangePassword(ctx, f.adminToken, "tutorial-only-password", "replacement-password")
	}()
	waitForBlocked(1)
	written := make(chan error, 1)
	go func() {
		_, err := f.service.CreateGroup(ctx, f.adminToken, "stale_actor", "Stale actor", "")
		written <- err
	}()
	waitForBlocked(2)
	if err := blocker.Commit(ctx); err != nil {
		t.Fatal(err)
	}
	if err := <-changed; err != nil {
		t.Fatal(err)
	}
	if err := <-written; !errors.Is(err, domain.ErrUnauthenticated) {
		t.Fatal("queued management write accepted a session revoked by password change", err)
	}
	var groups, audits int
	if err := f.pool.QueryRow(ctx, "SELECT count(*) FROM groups WHERE code='stale_actor'").Scan(&groups); err != nil || groups != 0 {
		t.Fatal("stale session created a group", groups, err)
	}
	if err := f.pool.QueryRow(ctx, "SELECT count(*) FROM auth_audit WHERE target_id='stale_actor'").Scan(&audits); err != nil || audits != 0 {
		t.Fatal("rejected write persisted an audit", audits, err)
	}
}
