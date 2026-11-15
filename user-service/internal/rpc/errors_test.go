package rpc

import (
	"errors"
	"fmt"
	"net"
	"testing"

	"github.com/JeanphiloGong/tsingai-lens/user-service/internal/domain"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
)

func TestRPCErrorContract(t *testing.T) {
	for _, item := range []struct {
		err     error
		code    codes.Code
		message string
	}{
		{fmt.Errorf("private context: %w", domain.ErrUnauthenticated), codes.Unauthenticated, "authentication_required"},
		{&net.OpError{Op: "dial", Net: "tcp", Err: errors.New("connection refused")}, codes.Unavailable, "identity_unavailable"},
		{errors.New("private diagnostic"), codes.Internal, "internal_error"},
	} {
		result := status.Convert(rpcError(item.err))
		if result.Code() != item.code || result.Message() != item.message {
			t.Fatal(result)
		}
	}
}
