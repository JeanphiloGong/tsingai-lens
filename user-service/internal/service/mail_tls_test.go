package service

import (
	"bufio"
	"context"
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/tls"
	"crypto/x509"
	"crypto/x509/pkix"
	"encoding/base64"
	"encoding/pem"
	"errors"
	"fmt"
	"math/big"
	"net"
	"net/textproto"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync/atomic"
	"testing"
	"time"
)

func TestSMTPTLSModes(t *testing.T) {
	// Each client gets a fresh system CA pool, with no test-only TLS override.
	if address := os.Getenv("LENS_TEST_SMTP_ADDRESS"); address != "" {
		sender := SMTPSettings{Address: address, From: "Lens <sender@example.test>",
			Username: "test-user", Password: "test-password", TLSMode: os.Getenv("LENS_TEST_SMTP_MODE")}
		if err := sender.Send(context.Background(), "recipient@example.test", "register", "001234"); err != nil {
			t.Fatal(err)
		}
		return
	}

	key, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	template := &x509.Certificate{SerialNumber: big.NewInt(1), Subject: pkix.Name{CommonName: "localhost"},
		DNSNames: []string{"localhost"}, NotBefore: time.Now().Add(-time.Hour), NotAfter: time.Now().Add(time.Hour),
		IsCA: true, BasicConstraintsValid: true, KeyUsage: x509.KeyUsageCertSign | x509.KeyUsageDigitalSignature,
		ExtKeyUsage: []x509.ExtKeyUsage{x509.ExtKeyUsageServerAuth}}
	der, err := x509.CreateCertificate(rand.Reader, template, template, &key.PublicKey, key)
	if err != nil {
		t.Fatal(err)
	}
	certificate := tls.Certificate{Certificate: [][]byte{der}, PrivateKey: key}
	directory := t.TempDir()
	caFile := filepath.Join(directory, "test-ca.crt")
	if err = os.WriteFile(caFile, pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: der}), 0600); err != nil {
		t.Fatal(err)
	}
	emptyCA := filepath.Join(directory, "empty-ca.crt")
	if err = os.WriteFile(emptyCA, nil, 0600); err != nil {
		t.Fatal(err)
	}
	emptyDirectory := t.TempDir()

	for _, test := range []struct {
		name, serverMode, clientMode, host, errorText string
		trusted                                       bool
	}{
		{"implicit TLS", "tls", "tls", "localhost", "", true},
		{"STARTTLS", "starttls", "starttls", "localhost", "", true},
		{"untrusted implicit TLS", "tls", "tls", "localhost", "certificate signed by unknown authority", false},
		{"untrusted STARTTLS", "starttls", "starttls", "localhost", "certificate signed by unknown authority", false},
		{"wrong hostname", "tls", "tls", "127.0.0.1", "cannot validate certificate for 127.0.0.1", true},
		{"no STARTTLS support", "none", "starttls", "localhost", "STARTTLS unavailable", true},
	} {
		t.Run(test.name, func(t *testing.T) {
			listener, err := net.Listen("tcp", "127.0.0.1:0")
			if err != nil {
				t.Fatal(err)
			}
			done := make(chan struct{})
			message := make(chan string, 1)
			var authenticated atomic.Bool
			go func() {
				defer close(done)
				connection, err := listener.Accept()
				if err != nil {
					return
				}
				defer connection.Close()
				connection.SetDeadline(time.Now().Add(5 * time.Second))
				encrypted := false
				config := &tls.Config{Certificates: []tls.Certificate{certificate}, MinVersion: tls.VersionTLS12}
				if test.serverMode == "tls" {
					secure := tls.Server(connection, config)
					if err = secure.Handshake(); err != nil {
						return
					}
					connection, encrypted = secure, true
				}
				fmt.Fprint(connection, "220 localhost test SMTP\r\n")
				reader := textproto.NewReader(bufio.NewReader(connection))
				for {
					line, err := reader.ReadLine()
					if err != nil {
						return
					}
					switch {
					case strings.HasPrefix(line, "EHLO"):
						if encrypted {
							fmt.Fprint(connection, "250-localhost\r\n250 AUTH PLAIN\r\n")
						} else if test.serverMode == "starttls" {
							fmt.Fprint(connection, "250-localhost\r\n250 STARTTLS\r\n")
						} else {
							fmt.Fprint(connection, "250 localhost\r\n")
						}
					case line == "STARTTLS" && test.serverMode == "starttls":
						fmt.Fprint(connection, "220 Ready for TLS\r\n")
						secure := tls.Server(connection, config)
						if err = secure.Handshake(); err != nil {
							return
						}
						connection, encrypted = secure, true
						reader = textproto.NewReader(bufio.NewReader(connection))
					case strings.HasPrefix(line, "AUTH PLAIN "):
						credentials, err := base64.StdEncoding.DecodeString(strings.TrimPrefix(line, "AUTH PLAIN "))
						if !encrypted || err != nil || string(credentials) != "\x00test-user\x00test-password" {
							t.Error("credentials were not sent over authenticated TLS")
							return
						}
						authenticated.Store(true)
						fmt.Fprint(connection, "235 Authenticated\r\n")
					case strings.HasPrefix(line, "MAIL FROM:"), strings.HasPrefix(line, "RCPT TO:"):
						if !authenticated.Load() {
							t.Error("mail submitted before authentication")
							return
						}
						fmt.Fprint(connection, "250 OK\r\n")
					case line == "DATA":
						fmt.Fprint(connection, "354 End with a dot\r\n")
						body, err := reader.ReadDotBytes()
						if err != nil {
							t.Error(err)
							return
						}
						message <- string(body)
						fmt.Fprint(connection, "250 Accepted\r\n")
					default:
						fmt.Fprint(connection, "500 STARTTLS unavailable\r\n")
					}
				}
			}()
			t.Cleanup(func() { listener.Close(); <-done })
			_, port, _ := net.SplitHostPort(listener.Addr().String())
			command := exec.Command(os.Args[0], "-test.run=^TestSMTPTLSModes$")
			root := caFile
			if !test.trusted {
				root = emptyCA
			}
			command.Env = append(os.Environ(), "LENS_TEST_SMTP_ADDRESS="+net.JoinHostPort(test.host, port),
				"LENS_TEST_SMTP_MODE="+test.clientMode, "SSL_CERT_FILE="+root, "SSL_CERT_DIR="+emptyDirectory)
			output, err := command.CombinedOutput()
			if test.errorText != "" {
				if err == nil || !strings.Contains(string(output), test.errorText) || authenticated.Load() {
					t.Fatalf("expected rejection before credentials: %v %s", err, output)
				}
				return
			}
			if err != nil {
				t.Fatalf("encrypted delivery failed: %v %s", err, output)
			}
			select {
			case body := <-message:
				for _, expected := range []string{"From: Lens <sender@example.test>", "To: recipient@example.test", "Subject: Lens register code", "001234"} {
					if !strings.Contains(body, expected) {
						t.Fatalf("message lacks %q", expected)
					}
				}
			default:
				t.Fatal("no message was captured")
			}
		})
	}
}

func TestSMTPTransportConfiguration(t *testing.T) {
	for _, test := range []struct{ mode, expected string }{
		{"none", "plaintext SMTP requires loopback"},
		{"invalid", "invalid SMTP_TLS_MODE"},
	} {
		sender := SMTPSettings{Address: "smtp.invalid:465", From: "sender@example.test", TLSMode: test.mode}
		if err := sender.Send(context.Background(), "recipient@example.test", "register", "001234"); err == nil || err.Error() != test.expected {
			t.Fatalf("unexpected configuration error: %v", err)
		}
	}
}

func TestSMTPHandshakeDeadline(t *testing.T) {
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 100*time.Millisecond)
	defer cancel()
	done := make(chan struct{})
	release := make(chan struct{})
	go func() {
		defer close(done)
		connection, err := listener.Accept()
		if err == nil {
			defer connection.Close()
			<-release
		}
	}()
	t.Cleanup(func() { close(release); listener.Close(); <-done })
	sender := SMTPSettings{Address: listener.Addr().String(), From: "sender@example.test", TLSMode: "tls"}
	start := time.Now()
	err = sender.Send(ctx, "recipient@example.test", "register", "001234")
	var networkError net.Error
	if err == nil || (!errors.Is(err, context.DeadlineExceeded) && !(errors.As(err, &networkError) && networkError.Timeout())) {
		t.Fatalf("expected handshake deadline error: %v", err)
	}
	if time.Since(start) > 2*time.Second {
		t.Fatal("handshake exceeded the caller's deadline")
	}
}
