package service

import (
	"bufio"
	"context"
	"fmt"
	"io"
	"net"
	"net/mail"
	"net/textproto"
	"regexp"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

// testMailbox speaks SMTP on a task-owned loopback socket; no external mail is sent.
type testMailbox struct {
	address  string
	reject   atomic.Bool
	mutex    sync.Mutex
	messages []*mail.Message
}

func newTestMailbox(t *testing.T) *testMailbox {
	t.Helper()
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	mailbox := &testMailbox{address: listener.Addr().String()}
	var connections sync.WaitGroup
	stopped := make(chan struct{})
	go func() {
		defer close(stopped)
		for {
			connection, err := listener.Accept()
			if err != nil {
				return
			}
			connections.Add(1)
			go func() {
				defer connections.Done()
				defer connection.Close()
				reader := textproto.NewReader(bufio.NewReader(connection))
				fmt.Fprint(connection, "220 localhost test SMTP\r\n")
				for {
					line, err := reader.ReadLine()
					if err != nil {
						return
					}
					switch {
					case strings.HasPrefix(line, "EHLO"), strings.HasPrefix(line, "HELO"), strings.HasPrefix(line, "MAIL FROM:"), strings.HasPrefix(line, "RCPT TO:"):
						fmt.Fprint(connection, "250 OK\r\n")
					case line == "DATA":
						fmt.Fprint(connection, "354 End with a dot\r\n")
						body, err := reader.ReadDotBytes()
						if err != nil {
							return
						}
						if mailbox.reject.Load() {
							fmt.Fprint(connection, "451 synthetic delivery failure\r\n")
							continue
						}
						message, err := mail.ReadMessage(strings.NewReader(string(body)))
						if err != nil {
							t.Error(err)
							return
						}
						mailbox.mutex.Lock()
						mailbox.messages = append(mailbox.messages, message)
						mailbox.mutex.Unlock()
						fmt.Fprint(connection, "250 Captured\r\n")
					case line == "QUIT":
						fmt.Fprint(connection, "221 Bye\r\n")
						return
					default:
						fmt.Fprint(connection, "500 Unsupported\r\n")
					}
				}
			}()
		}
	}()
	t.Cleanup(func() { listener.Close(); <-stopped; connections.Wait() })
	return mailbox
}

func (mailbox *testMailbox) codeFor(t *testing.T, email string) string {
	t.Helper()
	mailbox.mutex.Lock()
	defer mailbox.mutex.Unlock()
	for index := len(mailbox.messages) - 1; index >= 0; index-- {
		message := mailbox.messages[index]
		if message.Header.Get("To") != email {
			continue
		}
		body, err := io.ReadAll(message.Body)
		if err != nil {
			t.Fatal(err)
		}
		code := regexp.MustCompile(`\b[0-9]{6}\b`).FindString(string(body))
		if code == "" {
			t.Fatal("captured message has no verification code")
		}
		return code
	}
	t.Fatal("no message for test recipient", email)
	return ""
}

func TestSMTPMessageAndFailure(t *testing.T) {
	mailbox := newTestMailbox(t)
	sender := SMTPSettings{Address: mailbox.address, From: "Lens <noreply@example.test>", TLSMode: "none"}
	if err := sender.Send(context.Background(), "recipient@example.test", "register", "001234"); err != nil {
		t.Fatal(err)
	}
	if code := mailbox.codeFor(t, "recipient@example.test"); code != "001234" {
		t.Fatal("leading zero lost", code)
	}
	message := mailbox.messages[0]
	if message.Header.Get("From") != sender.From || message.Header.Get("Subject") != "Lens register code" || message.Header.Get("Content-Type") != "text/plain; charset=UTF-8" {
		t.Fatal("incorrect email headers", message.Header)
	}
	mailbox.reject.Store(true)
	if err := sender.Send(context.Background(), "recipient@example.test", "register", "123456"); err == nil {
		t.Fatal("SMTP rejection was ignored")
	}
}

func TestSMTPMessageHasDeliveryHeaders(t *testing.T) {
	mailbox := newTestMailbox(t)
	sender := SMTPSettings{Address: mailbox.address, From: "Lens <noreply@example.test>", TLSMode: "none"}
	started := time.Now().Truncate(time.Second)
	var previousID string
	for range 2 {
		if err := sender.Send(context.Background(), "recipient@example.test", "register", "001234"); err != nil {
			t.Fatal(err)
		}
		mailbox.mutex.Lock()
		message := mailbox.messages[len(mailbox.messages)-1]
		mailbox.mutex.Unlock()
		sentAt, err := mail.ParseDate(message.Header.Get("Date"))
		if err != nil || sentAt.Before(started) || sentAt.After(time.Now()) {
			t.Fatalf("message needs its actual origination date: %q", message.Header.Get("Date"))
		}
		messageID := message.Header.Get("Message-ID")
		if !regexp.MustCompile(`^<[a-zA-Z0-9_-]+@example\.test>$`).MatchString(messageID) || messageID == previousID {
			t.Fatalf("message needs a unique sender-domain identifier: %q", messageID)
		}
		previousID = messageID
		if message.Header.Get("MIME-Version") != "1.0" {
			t.Fatal("message needs MIME-Version for its declared UTF-8 content")
		}
	}
}
