package rpc

import (
	"context"
	"errors"

	"github.com/JeanphiloGong/tsingai-lens/user-service/internal/domain"
	pb "github.com/JeanphiloGong/tsingai-lens/user-service/internal/gen/userv1"
	"github.com/JeanphiloGong/tsingai-lens/user-service/internal/service"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
)

// declares `Server`, the struct ype whose `Resolve` method appears below
type Server struct {
	pb.UnimplementedIdentityServer
	Service *service.Service
}

// declares a helper that takes an `error` and returns an `error` suitable for the RPC response
func rpcError(err error) error {
	// replaces `err` with the result of classifying the original error before the helper inspects it
	err = service.ClassifyDependencyError(err)

	// declares a local pointer to a `domain.Error`, initially `nil`
	var businessError *domain.Error

	// checks whether `err`, including its err chain
	if errors.As(err, &businessError) {
		// selects a conversion based on the matched domain error's `Kind`
		switch businessError.Kind {
		case domain.Unauthenticated:
			return status.Error(codes.Unauthenticated, businessError.Code)
		case domain.Unavailable:
			return status.Error(codes.Unavailable, businessError.Code)
		}
	}
	return status.Error(codes.Internal, "internal_error")
}

// declares `Resolve` as a method on `*Server`;
func (s *Server) Resolve(ctx context.Context, request *pb.ResolveRequest) (*pb.ResolveReply, error) {
	// asks the Service to resolve the session from the request
	user, err := s.Service.Resolve(ctx, request.SessionToken)

	// checks whether the service reported a filure
	if err != nil {
		return nil, rpcError(err)
	}

	return &pb.ResolveReply{
		UserId:      user.ID,
		Email:       user.Email,
		DisplayName: user.Name,
	}, nil
}
