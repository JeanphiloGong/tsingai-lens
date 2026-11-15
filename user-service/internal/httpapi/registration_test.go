package httpapi

import (
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"net/textproto"
	"strings"
	"testing"

	"github.com/JeanphiloGong/tsingai-lens/user-service/internal/service"
)

func TestRegistrationInputAndOrigin(t *testing.T) {
	pool := testPool(t)
	identity := &service.Service{Pool: pool, RegistrationEnabled: true}
	handler := Router(identity, "http://localhost:5173", false, "")
	cases := []struct{ path, body, code string }{
		{"/v1/email-challenges", `{"email":"invalid","purpose":"register"}`, "invalid_request"},
		{"/v1/email-challenges", `{"email":"Person <a@example.test>","purpose":"register"}`, "invalid_request"},
		{"/v1/email-challenges", `{"email":"a@example.test","purpose":"other"}`, "invalid_request"},
		{"/v1/email-challenges", `{"email":"a@example.test","purpose":"register","group":"admin"}`, "invalid_request"},
		{"/v1/email-challenges", `{"email":"a@example.test","purpose":"register"} {}`, "invalid_request"},
		{"/v1/register", `{"email":"a@example.test","password":"short"}`, "invalid_request"},
		{"/v1/register", `{"email":"a@example.test","password":"tutorial-only-password","user_id":"admin"}`, "invalid_request"},
		{"/v1/register", `{"email":"a@example.test","password":"tutorial-only-password","permission_codes":[]}`, "invalid_request"},
		{"/v1/register", `{"email":"a@example.test","password":"` + strings.Repeat("p", 257) + `"}`, "invalid_request"},
		{"/v1/register", `{"email":"a@example.test","password":"tutorial-only-password","display_name":"` + strings.Repeat("n", 201) + `"}`, "invalid_request"},
		{"/v1/register", `{"email":"a@example.test","password":"tutorial-only-password","challenge_id":"missing","code":"123456"}`, "invalid_email_proof"},
		{"/v1/password-resets", `{"email":"a@example.test","password":"tutorial-only-password","challenge_id":"missing","code":"123456"}`, "invalid_email_proof"},
		{"/v1/password-resets", `{"email":"a@example.test","password":"tutorial-only-password","old_password":"ignored"}`, "invalid_request"},
	}
	for _, item := range cases {
		request := httptest.NewRequest(http.MethodPost, item.path, strings.NewReader(item.body))
		request.Header.Set("Origin", "http://localhost:5173")
		response := httptest.NewRecorder()
		handler.ServeHTTP(response, request)
		if response.Code != 422 || strings.TrimSpace(response.Body.String()) != `{"code":"`+item.code+`"}` {
			t.Fatalf("%s %d %s", item.path, response.Code, response.Body)
		}
	}
	for _, path := range []string{"/v1/email-challenges", "/v1/register", "/v1/password-resets"} {
		for _, origin := range []string{"", "https://untrusted.test"} {
			request := httptest.NewRequest(http.MethodPost, path, strings.NewReader(`{}`))
			request.Header.Set("Origin", origin)
			response := httptest.NewRecorder()
			handler.ServeHTTP(response, request)
			if response.Code != 403 {
				t.Fatal("cross-origin anonymous write accepted", path, response.Code)
			}
		}
	}
	var users int
	if err := pool.QueryRow(t.Context(), "SELECT count(*) FROM users").Scan(&users); err != nil || users != 0 {
		t.Fatal("invalid input created an account", users, err)
	}
}

func TestRegistrationSwitch(t *testing.T) {
	handler := Router(&service.Service{}, "http://localhost:5173", false, "")
	for _, path := range []string{"/v1/email-challenges", "/v1/register", "/v1/password-resets"} {
		request := httptest.NewRequest(http.MethodPost, path, strings.NewReader(`{}`))
		request.Header.Set("Origin", "http://localhost:5173")
		response := httptest.NewRecorder()
		handler.ServeHTTP(response, request)
		if response.Code != 403 || strings.TrimSpace(response.Body.String()) != `{"code":"permission_denied"}` {
			t.Fatal(path, response.Code, response.Body)
		}
	}
}

func TestRetryAfterErrorResponse(t *testing.T) {
	response := httptest.NewRecorder()
	writeError(response, fmt.Errorf("private rate detail: %w", &service.RateLimited{Seconds: 42}))
	var body ErrorResponse
	if err := json.Unmarshal(response.Body.Bytes(), &body); err != nil {
		t.Fatal(err)
	}
	if response.Code != 429 || response.Header().Get("Retry-After") != "42" || body.Code != "rate_limited" || body.RetryAfter != 42 {
		t.Fatal(response.Code, response.Header(), body)
	}
	for _, item := range []struct{ code, status int }{{451, 503}, {550, 500}} {
		response = httptest.NewRecorder()
		writeError(response, &textproto.Error{Code: item.code, Msg: "private mail diagnostic"})
		if response.Code != item.status || strings.Contains(response.Body.String(), "private") {
			t.Fatal(response.Code, response.Body)
		}
	}
}
