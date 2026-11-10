package domain

// Kind classifies business failures independently of their transport
type Kind string

const (
	Unauthenticated Kind = "unauthenticated"
	Forbidden       Kind = "forbidden"
	InvalidInput    Kind = "invalid_input"
	Conflict        Kind = "conflict"
	Unavailable     Kind = "unavailable"
)

func (k Kind) Error() string { return string(k) }

// Error carries a stabel public code. Its text never contains input or diagnostics
// Define these values once and treat them as immutable
type Error struct {
	Kind Kind
	Code string
}

func (e *Error) Error() string { return e.Code }
func (e *Error) Unwrap() error { return e.Kind }
