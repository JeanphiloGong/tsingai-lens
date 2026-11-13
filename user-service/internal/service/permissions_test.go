package service

import (
	"context"
	"errors"
	"sync"
	"testing"

	"github.com/JeanphiloGong/tsingai-lens/user-service/internal/domain"
	"github.com/jackc/pgx/v5"
)

func TestInitializeAdmin(t *testing.T) {
	ctx := context.Background()
	pool := testPool(t)
	identity := &Service{Pool: pool}
	if err := identity.Bootstrap(ctx, "initial@example.test", "tutorial-only-password"); err != nil {
		t.Fatal(err)
	}
	user, _, err := identity.Login(ctx, "initial@example.test", "tutorial-only-password")
	if err != nil {
		t.Fatal(err)
	}
	codes, err := identity.Permissions(ctx, user.ID)
	if err != nil || len(codes) != 0 {
		t.Fatal("bootstrap display name must not grant privileges", codes, err)
	}
	if err := identity.InitializeAdmin(ctx, "missing@example.test"); !errors.Is(err, pgx.ErrNoRows) {
		t.Fatal("missing user initialized", err)
	}
	if _, err := pool.Exec(ctx, "UPDATE users SET active=false WHERE user_id=$1", user.ID); err != nil {
		t.Fatal(err)
	}
	if err := identity.InitializeAdmin(ctx, user.Email); !errors.Is(err, ErrInvalid) {
		t.Fatal("disabled user initialized", err)
	}
	if _, err := pool.Exec(ctx, "UPDATE users SET active=true WHERE user_id=$1", user.ID); err != nil {
		t.Fatal(err)
	}
	if _, err := pool.Exec(ctx, `CREATE FUNCTION reject_initial_audit() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'synthetic audit failure'; END $$;
CREATE TRIGGER reject_initial_audit BEFORE INSERT ON auth_audit FOR EACH ROW EXECUTE FUNCTION reject_initial_audit();`); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		if _, err := pool.Exec(ctx, `DROP TRIGGER IF EXISTS reject_initial_audit ON auth_audit; DROP FUNCTION IF EXISTS reject_initial_audit();`); err != nil {
			t.Error(err)
		}
	})
	if err := identity.InitializeAdmin(ctx, user.Email); err == nil {
		t.Fatal("initialization ignored failed audit")
	}
	var memberships, audits int
	if err := pool.QueryRow(ctx, "SELECT count(*) FROM user_groups").Scan(&memberships); err != nil || memberships != 0 {
		t.Fatal("failed initialization left a membership", memberships, err)
	}
	if err := pool.QueryRow(ctx, "SELECT count(*) FROM auth_audit").Scan(&audits); err != nil || audits != 0 {
		t.Fatal("failed initialization left an audit", audits, err)
	}
	if _, err := pool.Exec(ctx, `DROP TRIGGER reject_initial_audit ON auth_audit; DROP FUNCTION reject_initial_audit();`); err != nil {
		t.Fatal(err)
	}

	start := make(chan struct{})
	results := make(chan error, 2)
	var workers sync.WaitGroup
	for range 2 {
		workers.Add(1)
		go func() {
			defer workers.Done()
			<-start
			results <- identity.InitializeAdmin(ctx, " INITIAL@example.test ")
		}()
	}
	close(start)
	workers.Wait()
	close(results)
	success, conflict := 0, 0
	for err := range results {
		switch {
		case err == nil:
			success++
		case errors.Is(err, ErrConflict):
			conflict++
		default:
			t.Fatal(err)
		}
	}
	if success != 1 || conflict != 1 {
		t.Fatal("concurrent initialization must succeed exactly once", success, conflict)
	}
	if err := pool.QueryRow(ctx, "SELECT count(*) FROM auth_audit WHERE actor_id=$1 AND target_id=$1 AND target_type='user' AND action='initialize_admin' AND details='{}'::jsonb", user.ID).Scan(&audits); err != nil || audits != 1 {
		t.Fatal("expected exactly one administrator initialization audit", audits, err)
	}
	allowed, err := identity.Check(ctx, user.ID, "users.manage")
	if err != nil || !allowed {
		t.Fatal("initialized user cannot manage", allowed, err)
	}
	if _, err := identity.Resolve(ctx, "invalid-session"); !errors.Is(err, domain.ErrUnauthenticated) {
		t.Fatal("initialization bypassed session authentication", err)
	}
}
