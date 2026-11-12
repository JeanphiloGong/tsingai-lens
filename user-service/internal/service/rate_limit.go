package service

import (
	"context"
	"time"

	"github.com/JeanphiloGong/tsingai-lens/user-service/internal/db"
	"github.com/JeanphiloGong/tsingai-lens/user-service/internal/domain"
)

type RateLimited struct{ Seconds int }

var errRateLimited = &domain.Error{Kind: domain.RateLimit, Code: "rate_limited"}

func (e *RateLimited) Error() string { return "rate_limited" }
func (e *RateLimited) Unwrap() error { return errRateLimited }

// declares the internal rule data consumed by `reserveRateLimits`
type rateRule struct {
	key              string
	seconds, maximum int32
}

// declares a helper that processes the supplied rules and returns one `error`
func reserveRateLimits(ctx context.Context, queries *db.Queries, rules ...rateRule) error {
	// begins processing each rule in caller-supplied order
	for _, rule := range rules {
		// asks the database query layer to reserve usage for the current rule
		row, err := queries.ReserveRate(ctx, db.ReserveRateParams{Key: rule.key, Seconds: rule.seconds})
		if err != nil {
			return err
		}

		// checks whether the current reservation has taken usage above the rule's maximum
		if row.Used > rule.maximum {
			// calculates a wait time for the `RateLimited` error
			seconds := int(time.Until(row.ResetAt.Time).Seconds()) + 1

			if seconds < 1 {
				seconds = 1
			}

			// stops processing at the first rule whose usage is over its maximum
			return &RateLimited{Seconds: seconds}
		}
	}
	return nil
}
