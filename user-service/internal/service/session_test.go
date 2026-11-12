package service

import (
	"context"
	"errors"
	"github.com/JeanphiloGong/tsingai-lens/user-service/internal/domain"
	"github.com/jackc/pgx/v5/pgxpool"
	"os"
	"strings"
	"sync"
	"testing"
)

// This test owns only the disposable TEST_USER_DATABASE_URL database.
func TestStoredSession(t *testing.T) {
	ctx := context.Background()
	pool := testPool(t)
	var err error
	service := Service{Pool: pool}
	if err = service.Bootstrap(ctx, "owner@example.test", "tutorial-only-password"); err != nil {
		t.Fatal(err)
	}
	user, sessionToken, err := service.Login(ctx, "owner@example.test", "tutorial-only-password")
	if err != nil {
		t.Fatal(err)
	}
	got, err := service.Resolve(ctx, sessionToken)
	if err != nil || got.ID != user.ID {
		t.Fatalf("resolve: %+v %v", got, err)
	}
	var stored string
	if err = pool.QueryRow(ctx, "SELECT token_hash FROM sessions").Scan(&stored); err != nil {
		t.Fatal(err)
	}
	if stored == sessionToken || stored != tokenHash(sessionToken) {
		t.Fatal("stored token must be a SHA-256 digest")
	}
	if err = service.Logout(ctx, sessionToken); err != nil {
		t.Fatal(err)
	}
	if _, err = service.Resolve(ctx, sessionToken); err != domain.ErrUnauthenticated {
		t.Fatalf("logout: %v", err)
	}
}

func TestBootstrapRules(t *testing.T) {
	ctx := context.Background()
	pool := testPool(t)
	account := &Service{Pool: pool}
	for _, input := range []struct{ email, password string }{
		{"owner@example.test", "short"},
		{"not-an-email", "tutorial-only-password"},
	} {
		if err := account.Bootstrap(ctx, input.email, input.password); !errors.Is(err, ErrInvalid) {
			t.Fatalf("invalid bootstrap: %v", err)
		}
	}
	var count int
	if err := pool.QueryRow(ctx, "SELECT count(*) FROM users").Scan(&count); err != nil || count != 0 {
		t.Fatal("invalid bootstrap wrote an account", count, err)
	}
	start := make(chan struct{})
	results := make(chan error, 2)
	var workers sync.WaitGroup
	for _, email := range []string{"first@example.test", "second@example.test"} {
		workers.Add(1)
		go func() {
			defer workers.Done()
			<-start
			results <- account.Bootstrap(ctx, email, "tutorial-only-password")
		}()
	}
	close(start)
	workers.Wait()
	close(results)
	succeeded, conflicted := 0, 0
	for err := range results {
		switch {
		case err == nil:
			succeeded++
		case errors.Is(err, ErrConflict):
			conflicted++
		default:
			t.Fatalf("concurrent bootstrap: %v", err)
		}
	}
	if err := pool.QueryRow(ctx, "SELECT count(*) FROM users").Scan(&count); err != nil || count != 1 || succeeded != 1 || conflicted != 1 {
		t.Fatal("bootstrap must create exactly one initial account", count, succeeded, conflicted, err)
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
	if _, err := pool.Exec(context.Background(), "TRUNCATE users CASCADE; TRUNCATE email_challenges, auth_rate_limits"); err != nil {
		t.Fatal(err)
	}
	return pool
}
