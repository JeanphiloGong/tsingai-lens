// starts a user-service process in one of two modes
// 1.Bootstram mode: if the sole command-line argument is `bootstrap`, it initializes the service using bootstrap credentials and then exits
// 2.HTTP mode: otherwise, it configures and starts and HTTP server, waits for a termination signal or a server-start failure, and attempts a timed shoudown
package main

import (
	"context"
	"log"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/JeanphiloGong/tsingai-lens/user-service/internal/httpapi"
	"github.com/JeanphiloGong/tsingai-lens/user-service/internal/service"
	"github.com/jackc/pgx/v5/pgxpool"
)

func required(key string) string {
	value := os.Getenv(key)
	if value == "" {
		log.Fatalf("missing %s", key)
	}
	return value
}

// declares `main`, the entry point go runs when the executable starts
func main() {
	// creates the context used to coordinate database work and process shutdown.
	ctx, cancel := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)

	// scheducles `cancel()` to run when `main` returns
	defer cancel()

	// creates the PostgreSQL connection pool that the service will use
	pool, err := pgxpool.New(ctx, required("USER_DATABASE_URL"))
	if err != nil {
		log.Fatal("invalid database configuration")
	}
	defer pool.Close()

	// checks database connectivity before either bootstrapping or serving requests
	if err = pool.Ping(ctx); err != nil {
		log.Fatal("database unavailable")
	}

	// constructs the service value used by both modes and gives it the pool created above
	userService := &service.Service{Pool: pool}

	// selects bootstrap mode only when there is exactly one argument after the executable name and that argument is `"bootstrap`
	if len(os.Args) == 2 && os.Args[1] == "bootstrap" {
		if err = userService.Bootstrap(ctx, required("BOOTSTRAP_EMAIL"), required("BOOTSTRAP_PASSWORD")); err != nil {
			log.Fatal(err)
		}
		return
	}

	// constructs the HTTP server used when bootstrap mode was not selected.
	server := &http.Server{
		Addr:              required("HTTP_ADDR"),
		Handler:           httpapi.Router(userService, required("BROWSER_ORIGIN"), os.Getenv("COOKIE_SECURE") != "false"),
		ReadHeaderTimeout: 5 * time.Second,
		ReadTimeout:       10 * time.Second,
		WriteTimeout:      15 * time.Second,
	}

	go func() {
		if err := server.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			log.Print(err)
			cancel()
		}
	}()
	// blocks the main goroutine until `ctx` is canceled
	<-ctx.Done()

	// creates a separate context for the shudown attempt, with a five-second deadline.
	shutdown, stop := context.WithTimeout(context.Background(), 5*time.Second)
	defer stop()
	if err := server.Shutdown(shutdown); err != nil {
		log.Print("HTTP shutdown did not finish: ", err)
	}

}
