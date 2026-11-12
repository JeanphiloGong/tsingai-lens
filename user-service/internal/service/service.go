package service

import (
	"context"
	"github.com/JeanphiloGong/tsingai-lens/user-service/internal/db"
	"github.com/jackc/pgx/v5/pgxpool"
)

type Service struct {
	Pool                *pgxpool.Pool
	RegistrationEnabled bool
	ChallengeSecret     string
	SMTP                SMTPSettings
}

func (s *Service) transaction(ctx context.Context, runQueries func(*db.Queries) error) error {
	tx, err := s.Pool.Begin(ctx)
	if err != nil {
		return err
	}
	defer tx.Rollback(ctx)
	if err = runQueries(db.New(tx)); err != nil {
		return err
	}
	return tx.Commit(ctx)
}
