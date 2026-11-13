package service

import (
	"context"
	"errors"
	"testing"
	"time"

	"github.com/JeanphiloGong/tsingai-lens/user-service/internal/domain"
)

func TestPasswordChangeRecoveryAndDisable(t *testing.T) {
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
	defer cancel()
	pool := testPool(t)
	mailbox := newTestMailbox(t)
	var err error
	identity := &Service{Pool: pool, RegistrationEnabled: true, ChallengeSecret: "local-test-secret-at-least-32-bytes", SMTP: SMTPSettings{Address: mailbox.address, From: "Lens <noreply@example.test>"}}
	password := "tutorial-only-password"
	if err = identity.Bootstrap(ctx, "operator@example.test", password); err != nil {
		t.Fatal(err)
	}
	if err = identity.InitializeAdmin(ctx, "operator@example.test"); err != nil {
		t.Fatal(err)
	}
	admin, adminToken, err := identity.Login(ctx, "operator@example.test", password)
	if err != nil {
		t.Fatal(err)
	}
	email := "recovery-race@example.test"
	// A verified fixture isolates credential locking; browser tests cover actual signup.
	if _, err = pool.Exec(ctx, `INSERT INTO users(user_id,email,password_hash,email_verified_at) SELECT 'recovery-race',$1,password_hash,now() FROM users WHERE user_id=$2`, email, admin.ID); err != nil {
		t.Fatal(err)
	}
	user, token, err := identity.Login(ctx, email, password)
	if err != nil {
		t.Fatal(err)
	}
	challengeID, err := identity.IssueEmailChallenge(ctx, email, "password_reset", "race-test")
	if err != nil {
		t.Fatal(err)
	}
	code := mailbox.codeFor(t, email)
	selfResult, resetResult := make(chan error, 1), make(chan error, 1)
	go func() { selfResult <- identity.ChangePassword(ctx, token, password, "self-changed-password") }()
	go func() {
		_, err := identity.CompleteEmailChallenge(ctx, challengeID, email, "password_reset", code, "recovered-password", "", "race-test")
		resetResult <- err
	}()
	if err = <-resetResult; err != nil {
		t.Fatal(err)
	}
	if err = <-selfResult; err != nil && !errors.Is(err, domain.ErrUnauthenticated) {
		t.Fatal(err)
	}
	if _, err = identity.Resolve(ctx, token); !errors.Is(err, domain.ErrUnauthenticated) {
		t.Fatal("old session survived recovery", err)
	}
	_, token, err = identity.Login(ctx, email, "recovered-password")
	if err != nil {
		t.Fatal("stale self-change overwrote recovery", err)
	}
	disableResult := make(chan error, 1)
	go func() {
		selfResult <- identity.ChangePassword(ctx, token, "recovered-password", "another-self-password")
	}()
	go func() { _, err := identity.UpdateUserStatus(ctx, adminToken, user.ID, false); disableResult <- err }()
	if err = <-disableResult; err != nil {
		t.Fatal(err)
	}
	if err = <-selfResult; err != nil && !errors.Is(err, domain.ErrUnauthenticated) {
		t.Fatal(err)
	}
	if _, err = identity.Resolve(ctx, token); !errors.Is(err, domain.ErrUnauthenticated) {
		t.Fatal("disabled session survived", err)
	}
	if _, _, err = identity.Login(ctx, email, "another-self-password"); !errors.Is(err, domain.ErrUnauthenticated) {
		t.Fatal("disabled account logged in", err)
	}
}
