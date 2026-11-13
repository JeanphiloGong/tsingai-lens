// starts a user-service process in one of two modes
// 1.Bootstram mode: if the sole command-line argument is `bootstrap`, it initializes the service using bootstrap credentials and then exits
// 2.HTTP mode: otherwise, it configures and starts and HTTP server, waits for a termination signal or a server-start failure, and attempts a timed shoudown
package main

import (
	"context"
	"crypto/tls"
	"crypto/x509"
	pb "github.com/JeanphiloGong/tsingai-lens/user-service/internal/gen/userv1"
	"log"
	"net"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/JeanphiloGong/tsingai-lens/user-service/internal/httpapi"
	"github.com/JeanphiloGong/tsingai-lens/user-service/internal/rpc"
	"github.com/JeanphiloGong/tsingai-lens/user-service/internal/service"
	"github.com/jackc/pgx/v5/pgxpool"
	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials"
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

	if os.Getenv("REGISTRATION_ENABLED") == "true" {
		userService.RegistrationEnabled = true
		userService.ChallengeSecret = required("CHALLENGE_SECRET")
		if len(userService.ChallengeSecret) < 32 {
			log.Fatal("CHALLENGE_SECRET needs at least 32 bytes")
		}
		userService.SMTP = service.SMTPSettings{
			Address:  required("SMTP_ADDR"),
			From:     required("SMTP_FROM"),
			Username: os.Getenv("SMTP_USER"),
			Password: os.Getenv("SMTP_PASSWORD"),
			TLS:      os.Getenv("SMTP_TLS") != "false",
		}
	}

	// loads the certificate and matching private key that the gRPC server will present during TLS handshakes
	serverCert, err := tls.LoadX509KeyPair(required("RPC_CERT"), required("RPC_KEY"))

	// checks whether loading the server certificate and key failed
	if err != nil {
		log.Fatal(err)
	}

	// reads the configured client CA file so its certificates can be added to the trust pool
	caPEM, err := os.ReadFile(required("RPC_CA"))

	// checks whether reading the CA file failed.
	if err != nil {
		log.Fatal(err)
	}

	// creates an initially empty certificate pool to hold the CAs used for client-certificate verification
	clientCAs := x509.NewCertPool()

	// attempts to add certificates from the file bytes to `clientAs` and rejects the configuration if none can be parsed successfully
	if !clientCAs.AppendCertsFromPEM(caPEM) {
		log.Fatal("invalid CA")
	}

	// construts the gRPC server with TLS transport credentials
	rpcServer := grpc.NewServer(
		// &tls.Config creates a TLS configuation and passes a pointer to it
		grpc.Creds(credentials.NewTLS(&tls.Config{
			// set TLS 1.3 as the minimum accepted protocol version
			MinVersion: tls.VersionTLS13,
			// creates a slice containing the certificate and private key loaded earlier
			Certificates: []tls.Certificate{
				serverCert,
			},
			// supplies the pool used to verify client certificates
			ClientCAs: clientCAs,
			// requires clients to present a certificated and requires that certificate
			ClientAuth: tls.RequireAndVerifyClientCert,
		})),
	)
	// registers an identity-service implementation with the newly created gRPC server
	pb.RegisterIdentityServer(rpcServer, &rpc.Server{Service: userService})

	// opens the network endpoint on which the gRPC server will accept connections
	listener, err := net.Listen("tcp", required("RPC_ADDR"))

	// checks whether the TCP listener could be created
	if err != nil {
		log.Fatal(err)
	}

	// starts an anonymous function in a new goroutine
	go func() {
		if err := rpcServer.Serve(listener); err != nil {
			log.Print(err)
			cancel()
		}
	}()

	// schedules `rpcServerStop()` to run when `main` returns normally or unwinds through a panic
	defer rpcServer.Stop()

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
