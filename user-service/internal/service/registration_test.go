package service

import (
	"context"
	"errors"
	"fmt"
	"github.com/JeanphiloGong/tsingai-lens/user-service/internal/domain"
	"sync"
	"testing"
	"time"
)

func TestRegistration(t *testing.T) {
	ctx := context.Background()
	pool := testPool(t)
	mailbox := newTestMailbox(t)
	s := Service{Pool: pool, RegistrationEnabled: true, ChallengeSecret: "local-test-secret-at-least-32-bytes", SMTP: SMTPSettings{Address: mailbox.address, From: "Lens <noreply@example.test>", TLSMode: "none"}}
	codeFor := func(email string) string { return mailbox.codeFor(t, email) }
	var err error
	issue := func(email, purpose string) (string, string) {
		challengeID, err := s.IssueEmailChallenge(ctx, email, purpose, "service-test")
		if err != nil {
			t.Fatal(err)
		}
		return challengeID, codeFor(email)
	}
	password := "tutorial-only-password"
	email := fmt.Sprintf("registration-%d@example.test", time.Now().UnixNano())
	challengeID, verificationCode := issue(email, "register")
	_, err = s.IssueEmailChallenge(ctx, email, "register", "service-test")
	var limited *RateLimited
	if !errors.As(err, &limited) {
		t.Fatal("cooldown did not reject", err)
	}
	var success int
	var mutex sync.Mutex
	var wg sync.WaitGroup
	for range 2 {
		wg.Add(1)
		go func() {
			defer wg.Done()
			_, err := s.CompleteEmailChallenge(ctx, challengeID, email, "register", verificationCode, password, "Researcher", "service-test")
			mutex.Lock()
			defer mutex.Unlock()
			if err == nil {
				success++
			} else if !errors.Is(err, domain.ErrChallenge) {
				t.Error(err)
			}
		}()
	}
	wg.Wait()
	if success != 1 {
		t.Fatal("concurrent proof use", success)
	}
	user, sessionToken, err := s.Login(ctx, email, password)
	if err != nil {
		t.Fatal(err)
	}
	perms, err := s.Permissions(ctx, user.ID)
	if err != nil || len(perms) != 0 {
		t.Fatal("registration granted privileges", perms, err)
	}
	resetID, resetCode := issue(email, "password_reset")
	if _, err = s.CompleteEmailChallenge(ctx, challengeID, email, "password_reset", verificationCode, "new-tutorial-password", "", "service-test"); err != domain.ErrChallenge {
		t.Fatal("purpose reuse", err)
	}
	if _, err = s.CompleteEmailChallenge(ctx, resetID, email, "password_reset", resetCode, "new-tutorial-password", "", "service-test"); err != nil {
		t.Fatal(err)
	}
	if _, err = s.Resolve(ctx, sessionToken); err != domain.ErrUnauthenticated {
		t.Fatal("old session survived", err)
	}
	if _, _, err = s.Login(ctx, email, password); err != domain.ErrUnauthenticated {
		t.Fatal("old password survived", err)
	}
	if _, _, err = s.Login(ctx, email, "new-tutorial-password"); err != nil {
		t.Fatal(err)
	}
	wrongEmail := fmt.Sprintf("wrong-%d@example.test", time.Now().UnixNano())
	wrongChallengeID, wrongChallengeCode := issue(wrongEmail, "register")
	wrong := "000000"
	if wrong == wrongChallengeCode {
		wrong = "111111"
	}
	for range 5 {
		if _, err = s.CompleteEmailChallenge(ctx, wrongChallengeID, wrongEmail, "register", wrong, password, "", "service-test"); err != domain.ErrChallenge {
			t.Fatal(err)
		}
	}
	var attempts int
	if err = pool.QueryRow(ctx, "SELECT attempts FROM email_challenges WHERE challenge_id=$1", wrongChallengeID).Scan(&attempts); err != nil || attempts != 5 {
		t.Fatal("wrong attempts rolled back", attempts, err)
	}
	if _, err = s.CompleteEmailChallenge(ctx, wrongChallengeID, wrongEmail, "register", wrongChallengeCode, password, "", "service-test"); err != domain.ErrChallenge {
		t.Fatal("exhausted proof accepted", err)
	}
	if _, err = pool.Exec(ctx, "UPDATE auth_rate_limits SET reset_at=now()-interval '1 second' WHERE key=$1", "cooldown:register:"+wrongEmail); err != nil {
		t.Fatal(err)
	}
	newer, newCode := issue(wrongEmail, "register")
	if newer == wrongChallengeID {
		t.Fatal("challenge not replaced")
	}
	if _, err = s.CompleteEmailChallenge(ctx, wrongChallengeID, wrongEmail, "register", wrongChallengeCode, password, "", "service-test"); err != domain.ErrChallenge {
		t.Fatal("old challenge resurrected", err)
	}
	if _, err = pool.Exec(ctx, "UPDATE email_challenges SET expires_at=now() WHERE challenge_id=$1", newer); err != nil {
		t.Fatal(err)
	}
	if _, err = s.CompleteEmailChallenge(ctx, newer, wrongEmail, "register", newCode, password, "", "service-test"); err != domain.ErrChallenge {
		t.Fatal("expired proof accepted", err)
	}
	// Old/operator accounts have no verified_at and cannot be recovered by email.
	if _, err = pool.Exec(ctx, "INSERT INTO users(user_id,email,password_hash) VALUES('legacy','legacy@example.test','!')"); err != nil {
		t.Fatal(err)
	}
	opaque, err := s.IssueEmailChallenge(ctx, "legacy@example.test", "password_reset", "service-test")
	if err != nil {
		t.Fatal(err)
	}
	if _, err = s.CompleteEmailChallenge(ctx, opaque, "legacy@example.test", "password_reset", "123456", password, "", "service-test"); err != domain.ErrChallenge {
		t.Fatal("unverified recovery", err)
	}
	// Actual SMTP rejection must leave a failed challenge and never an account.
	mailbox.reject.Store(true)
	_, err = s.IssueEmailChallenge(ctx, "failed@example.test", "register", "service-test")
	if err == nil {
		t.Fatal("SMTP rejection ignored")
	}
	var state string
	if err = pool.QueryRow(ctx, "SELECT state FROM email_challenges WHERE email='failed@example.test'").Scan(&state); err != nil || state != "failed" {
		t.Fatal("failure state", state, err)
	}
	// A fresh service instance shares durable counters.
	reloaded := s
	if _, err = reloaded.IssueEmailChallenge(ctx, "failed@example.test", "register", "service-test"); !errors.As(err, &limited) {
		t.Fatal("restart bypassed cooldown", err)
	}
}

func TestEmailChallengeTransactionRollback(t *testing.T) {
	ctx := context.Background()
	pool := testPool(t)
	mailbox := newTestMailbox(t)
	identity := Service{Pool: pool, RegistrationEnabled: true, ChallengeSecret: "local-test-secret-at-least-32-bytes", SMTP: SMTPSettings{Address: mailbox.address, From: "Lens <noreply@example.test>", TLSMode: "none"}}
	email, password := "atomic@example.test", "tutorial-only-password"
	challengeID, err := identity.IssueEmailChallenge(ctx, email, "register", "atomic-test")
	if err != nil {
		t.Fatal(err)
	}
	code := mailbox.codeFor(t, email)
	_, err = pool.Exec(ctx, `CREATE FUNCTION reject_challenge_consumption() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.state='consumed' THEN RAISE EXCEPTION 'synthetic consume failure'; END IF; RETURN NEW; END $$;
CREATE TRIGGER reject_challenge_consumption BEFORE UPDATE ON email_challenges FOR EACH ROW EXECUTE FUNCTION reject_challenge_consumption();`)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		if _, err := pool.Exec(ctx, `DROP TRIGGER IF EXISTS reject_challenge_consumption ON email_challenges;DROP FUNCTION IF EXISTS reject_challenge_consumption()`); err != nil {
			t.Error(err)
		}
	})
	if _, err = identity.CompleteEmailChallenge(ctx, challengeID, email, "register", code, password, "", "atomic-test"); err == nil {
		t.Fatal("registration ignored failed proof consumption")
	}
	var count int
	var state string
	if err = pool.QueryRow(ctx, "SELECT count(*) FROM users").Scan(&count); err != nil || count != 0 {
		t.Fatal("partial registration persisted", count, err)
	}
	if err = pool.QueryRow(ctx, "SELECT state FROM email_challenges WHERE challenge_id=$1", challengeID).Scan(&state); err != nil || state != "sent" {
		t.Fatal(state, err)
	}
	if _, err = pool.Exec(ctx, "ALTER TABLE email_challenges DISABLE TRIGGER reject_challenge_consumption"); err != nil {
		t.Fatal(err)
	}
	if _, err = identity.CompleteEmailChallenge(ctx, challengeID, email, "register", code, password, "", "atomic-test"); err != nil {
		t.Fatal(err)
	}
	_, token, err := identity.Login(ctx, email, password)
	if err != nil {
		t.Fatal(err)
	}
	resetID, err := identity.IssueEmailChallenge(ctx, email, "password_reset", "atomic-test")
	if err != nil {
		t.Fatal(err)
	}
	resetCode := mailbox.codeFor(t, email)
	if _, err = pool.Exec(ctx, "ALTER TABLE email_challenges ENABLE TRIGGER reject_challenge_consumption"); err != nil {
		t.Fatal(err)
	}
	if _, err = identity.CompleteEmailChallenge(ctx, resetID, email, "password_reset", resetCode, "replacement-password", "", "atomic-test"); err == nil {
		t.Fatal("recovery ignored failed proof consumption")
	}
	if _, err = identity.Resolve(ctx, token); err != nil {
		t.Fatal("failed recovery revoked session", err)
	}
	if _, _, err = identity.Login(ctx, email, password); err != nil {
		t.Fatal("failed recovery changed password", err)
	}
	if err = pool.QueryRow(ctx, "SELECT state FROM email_challenges WHERE challenge_id=$1", resetID).Scan(&state); err != nil || state != "sent" {
		t.Fatal("failed recovery consumed proof", state, err)
	}
}
