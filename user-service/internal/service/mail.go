package service

import (
	"context"
	"crypto/tls"
	"fmt"
	"log/slog"
	"net"
	"net/mail"
	"net/smtp"
	"strings"
	"time"
)

// SMTPSettings belongs to this concrete transport, not to hte email-proof model
type SMTPSettings struct {
	Address  string
	From     string
	Username string
	Password string
	TLSMode  string
}

// declares a method of `SMTPSettings` that validates the configured sender address, opens a time-limited TCP connection, optionally starts TLS and authenticates, then submits the sender, recipient, and message
func (s SMTPSettings) Send(ctx context.Context, email, purpose, verificationCode string) error {
	// parses the configured sender so the SMTP envelope can later use its email address
	from, err := mail.ParseAddress(s.From)

	// checks whether parsing failed
	if err != nil {
		return err
	}

	// separates the configured server address into a host and port
	host, _, err := net.SplitHostPort(s.Address)

	// checks whether `s.Address` could be split into a host and port
	if err != nil {
		return err
	}

	// Select the configured transport before connecting; plaintext is local-only.
	switch s.TLSMode {
	case "tls", "starttls":
	case "none":
		if ip := net.ParseIP(host); ip == nil || !ip.IsLoopback() {
			return fmt.Errorf("plaintext SMTP requires loopback")
		}
	default:
		return fmt.Errorf("invalid SMTP_TLS_MODE")
	}

	// prepares a network dialer with a five-second timeout for establishing the connection
	dial := net.Dialer{Timeout: 5 * time.Second}

	// attempts to connect to the configured SMTP server
	conn, err := dial.DialContext(ctx, "tcp", s.Address)

	// checks whether the connection attempt failed, including because of a timeout, context cancellation, or a network error
	if err != nil {
		return err
	}

	// schedules the connection to be closed when `Send` returns, including on a later error
	defer conn.Close()

	// sets an initial absolute deadline five seconds from the current time
	deadline := time.Now().Add(5 * time.Second)

	// checks whether the context has an earlier deadline and selects it instead
	if requestDeadline, ok := ctx.Deadline(); ok && requestDeadline.Before(deadline) {
		deadline = requestDeadline
	}

	// applies the chosen absolute deadline to both reads and writes on `conn`
	if err = conn.SetDeadline(deadline); err != nil {
		return err
	}

	tlsConfig := &tls.Config{ServerName: host, MinVersion: tls.VersionTLS12}
	if s.TLSMode == "tls" {
		// Implicit TLS completes its handshake before reading the SMTP greeting.
		tlsConn := tls.Client(conn, tlsConfig)
		if err = tlsConn.HandshakeContext(ctx); err != nil {
			return err
		}
		conn = tlsConn
	}

	// creates an SMTP client over the established connection, using `host` as the server name
	client, err := smtp.NewClient(conn, host)

	// checks whether SMTP client initialization or the initial greeting failed
	if err != nil {
		return err
	}

	// schedules the SMTP client to be closed when `Send` returns.
	defer client.Close()

	// STARTTLS upgrades an SMTP connection before any credentials are submitted.
	if s.TLSMode == "starttls" {
		// requests STARTTLS and checks whether it succeeds
		if err = client.StartTLS(tlsConfig); err != nil {
			return err
		}
	}

	// decides whether to authenticate
	if s.Username != "" {
		// creates a PLAIN authentication mechanism and asks the SMTP client to use it
		if err = client.Auth(smtp.PlainAuth("", s.Username, s.Password, host)); err != nil {
			return err
		}
	}

	// sends the SMTP `MAIL FROM` command and checks its result
	if err = client.Mail(from.Address); err != nil {
		return err
	}

	// submits `email` as the SMTP envelope recipient and checks the result
	if err = client.Rcpt(email); err != nil {
		return err
	}

	// starts the SMTP `DATA` phase and obtains a writer for the message's headers and body
	writer, err := client.Data()
	if err != nil {
		return err
	}

	// formats and writes the email headers and plain-text body to the SMTP data writer
	messageID := fmt.Sprintf("<%s@%s>", randomID(), from.Address[strings.LastIndexByte(from.Address, '@')+1:])
	_, err = fmt.Fprintf(writer,
		"Date: %s\r\n"+
			"Message-ID: %s\r\n"+
			"From: %s\r\nTo: %s\r\n"+
			"Subject: Lens %s code\r\n"+
			"MIME-Version: 1.0\r\nContent-Type: text/plain; charset=UTF-8\r\n"+
			"\r\n Your Lens %s code is %s. It expires in 10 minutes.\r\n",
		time.Now().Format(time.RFC1123Z), messageID, s.From, email, purpose, purpose, verificationCode)
	if err != nil {
		return err
	}

	// Closing DATA waits for the provider's acceptance, not the recipient's delivery.
	if err = writer.Close(); err != nil {
		return err
	}
	slog.Info("verification email accepted by SMTP", "message_id", messageID, "purpose", purpose)
	return nil
}
