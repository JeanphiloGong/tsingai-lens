package service

import (
	"context"
	"testing"
)

func TestModelAdministrationCanBeRevokedIndependently(t *testing.T) {
	ctx := context.Background()
	pool := testPool(t)
	identity := &Service{Pool: pool}
	if err := identity.Bootstrap(ctx, "model-admin@example.test", "tutorial-only-password"); err != nil {
		t.Fatal(err)
	}
	if err := identity.InitializeAdmin(ctx, "model-admin@example.test"); err != nil {
		t.Fatal(err)
	}
	user, _, err := identity.Login(ctx, "model-admin@example.test", "tutorial-only-password")
	if err != nil {
		t.Fatal(err)
	}
	allowed, err := identity.Check(ctx, user.ID, "models.manage")
	if err != nil || !allowed {
		t.Fatal("model permission migration did not reach the administrator", allowed, err)
	}
	if _, err = pool.Exec(ctx, "DELETE FROM group_permissions WHERE group_code='admin' AND permission_code='models.manage'"); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		if _, err := pool.Exec(ctx, "INSERT INTO group_permissions VALUES ('admin','models.manage') ON CONFLICT DO NOTHING"); err != nil {
			t.Error(err)
		}
	})
	allowed, err = identity.Check(ctx, user.ID, "models.manage")
	if err != nil || allowed {
		t.Fatal("model grant did not revoke immediately", allowed, err)
	}
	allowed, err = identity.Check(ctx, user.ID, "users.manage")
	if err != nil || !allowed {
		t.Fatal("independent personnel permission was changed", allowed, err)
	}
	if err = identity.InitializeAdmin(ctx, user.Email); err == nil {
		t.Fatal("initialization unexpectedly ran again")
	}
	allowed, err = identity.Check(ctx, user.ID, "models.manage")
	if err != nil || allowed {
		t.Fatal("initialization restored a revoked model grant", allowed, err)
	}
}
