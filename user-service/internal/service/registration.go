package service

import (
	"context"
	"crypto/hmac"
	"crypto/rand"
	"crypto/sha256"
	"errors"
	"fmt"
	"math/big"
	"net/mail"
	"strings"
	"time"

	"github.com/JeanphiloGong/tsingai-lens/user-service/internal/db"
	"github.com/JeanphiloGong/tsingai-lens/user-service/internal/domain"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"
)

// declares a function that tasks an email string, trims surrounding whitespace, converts it to lowercase
func normalizedEmail(email string) (string, error) {
	email = strings.ToLower(strings.TrimSpace(email))
	// asks `mail.ParseAddress` to parse the normalized string
	parsed, err := mail.ParseAddress(email)

	// selects the rejection path if any of three checks fails
	if err != nil || parsed.Address != email || len(email) > 254 {
		return "", ErrInvalid
	}

	return email, nil
}

// declares a function that takes a challenge ID, email, purpose, and verification code and computes a keyed
func (s *Service) challengeCodeDigest(challengeID, email, purpose, verificationCode string) []byte {
	// creates a new HMAC calculator using sha-256 and the service's challenge secret as its key.
	mac := hmac.New(sha256.New, []byte(s.ChallengeSecret))

	// writes the four input string into `mac` in the order `challengeID`, `email`, `purpose`, `verificationCode`
	fmt.Fprintf(mac, "%s\x00%s\x00%s\x00%s", challengeID, email, purpose, verificationCode)

	// finishes the method by returning the HMAC digest for the bytes written above
	return mac.Sum(nil)
}

// declares a function that normalizes and validates the request, generates an ID and six-digit code, then uses a transaction to reserve rate limits and checks whether the email is eligible
func (s *Service) IssueEmailChallenge(ctx context.Context, email, purpose, clientIP string) (string, error) {
	// checks whether the service permits this operation before doing any other work
	if !s.RegistrationEnabled {
		return "", ErrForbidden
	}

	// replaces the local `email` value with the result of normalizing the supplied address and captures any error for the next check
	email, err := normalizedEmail(email)

	// tests whether normalization reported a failure
	if err != nil {
		return "", err
	}

	// accepts only the two purpose
	if purpose != "register" && purpose != "password_reset" {
		return "", ErrInvalid
	}

	// declares a local challenge ID
	challengeID := randomID()

	// genereates the numeric value from which the verification code will be formatted
	number, err := rand.Int(rand.Reader, big.NewInt(1000000))
	if err != nil {
		return "", err
	}

	// creates teh six-charecter decimal code that will be sent to an eligible recipient and included in the digest calculation
	verificationCode := fmt.Sprintf("%06d", number.Int64())

	// declares a Boolean that will carry the eligibility decision out of the transaction callback
	eligible := false

	err = s.transaction(ctx, func(queries *db.Queries) error {
		if err := reserveRateLimits(
			ctx,
			queries,
			rateRule{"send-ip:" + clientIP, 3600, 20},
			rateRule{"send-email:" + email, 3600, 5},
			rateRule{"cooldown:" + purpose + ":" + email, 60, 1},
		); err != nil {
			return err
		}

		// asks the transaction's query object to lock the normalized email before making the eligibility decision
		if err := queries.LockEmail(ctx, email); err != nil {
			return err
		}

		// selects teh registration eligibility check
		if purpose == "register" {
			_, err := queries.UserByEmail(ctx, email)
			if err != nil && !errors.Is(err, pgx.ErrNoRows) {
				return err
			}

			// sets the outer `elibible` variable to the registration decision
			eligible = errors.Is(err, pgx.ErrNoRows)
		} else {
			var err error

			// asks whether the normalized email is eligible for password reset
			eligible, err = queries.CanResetEmail(ctx, email)

			if err != nil {
				return err
			}
		}
		// checks the decision from either eligibility path
		if !eligible {
			return nil
		}
		return queries.PutChallenge(
			ctx,
			db.PutChallengeParams{
				ChallengeID: challengeID,
				Email:       email,
				Purpose:     purpose,
				CodeDigest:  s.challengeCodeDigest(challengeID, email, purpose, verificationCode),
			},
		)
	})
	if err != nil {
		return "", err
	}

	if !eligible {
		return challengeID, nil
	}

	// attempts to send the plaintext verification code only after an eligible challenge has been stored and the trasaction has returned without error
	if err = s.SMTP.Send(ctx, email, purpose, verificationCode); err != nil {
		// creates a separate context for the failure-marking attempt
		markCtx, cancel := context.WithTimeout(context.WithoutCancel(ctx), 2*time.Second)
		// schedules `cancel` to run
		defer cancel()

		// makes a best-effort attempt to mark the challenge failed after the send error
		_ = db.New(s.Pool).MarkFailed(markCtx, challengeID)
		return "", err
	}
	// after send reports success, asks the database to mark the challenge as sent
	affectedRows, err := db.New(s.Pool).MarkSent(ctx, challengeID)

	if err != nil {
		return "", err
	}

	if affectedRows != 1 {
		return "", ErrConflict
	}

	return challengeID, nil
}

// CompleteEmailChallenge commits an invalid proof's attempt separately from the response error.
// For a valid proof, consuming it and changing the account share this transaction.
func (s *Service) CompleteEmailChallenge(ctx context.Context, challengeID, email, purpose, verificationCode, password, displayName, clientIP string) (domain.User, error) {
	if !s.RegistrationEnabled {
		return domain.User{}, ErrForbidden
	}
	email, err := normalizedEmail(email)
	if err != nil {
		return domain.User{}, err
	}
	if len(password) < 12 || len(password) > 256 || len(displayName) > 200 {
		return domain.User{}, ErrInvalid
	}
	if purpose != "register" && purpose != "password_reset" {
		return domain.User{}, ErrInvalid
	}
	var user domain.User
	var proofErr error
	err = s.transaction(ctx, func(queries *db.Queries) error {
		if err := reserveRateLimits(ctx, queries, rateRule{"verify-ip:" + clientIP, 900, 60}, rateRule{"verify-email:" + email, 900, 20}); err != nil {
			return err
		}
		if err := queries.LockEmail(ctx, email); err != nil {
			return err
		}
		row, err := queries.ChallengeByEmail(ctx, db.ChallengeByEmailParams{Email: email, Purpose: purpose})
		if errors.Is(err, pgx.ErrNoRows) {
			proofErr = domain.ErrChallenge
			return nil
		}
		if err != nil {
			return err
		}
		proof := domain.EmailChallenge{ID: row.ChallengeID, Email: row.Email, Purpose: row.Purpose, State: row.State, ExpiresAt: row.ExpiresAt.Time, Attempts: row.Attempts}
		if err = proof.Check(challengeID, email, purpose, time.Now()); err != nil {
			proofErr = err
			return nil
		}
		if !hmac.Equal(row.CodeDigest, s.challengeCodeDigest(challengeID, email, purpose, verificationCode)) {
			if err = queries.WrongAttempt(ctx, row.ChallengeID); err != nil {
				return err
			}
			proofErr = domain.ErrChallenge
			return nil // commit attempt and rate counters before returning422
		}
		encodedPasswordHash, err := passwordHash(password)
		if err != nil {
			return err
		}
		if purpose == "register" {
			existingUserRow, err := queries.UserByEmail(ctx, email)
			if err == nil && existingUserRow.UserID != "" {
				return ErrConflict
			}
			if err != nil && !errors.Is(err, pgx.ErrNoRows) {
				return err
			}
			user = domain.User{ID: "user_" + randomID()[:24], Email: email, Name: strings.TrimSpace(displayName), Active: true}
			if err = queries.RegisterUser(ctx, db.RegisterUserParams{UserID: user.ID, Email: email, DisplayName: user.Name, PasswordHash: encodedPasswordHash}); err != nil {
				var databaseError *pgconn.PgError
				if errors.As(err, &databaseError) && databaseError.Code == "23505" && databaseError.ConstraintName == "users_email_key" {
					return fmt.Errorf("register user: %w: %w", ErrConflict, err)
				}
				return err
			}
		} else {
			userRow, err := queries.UserByEmail(ctx, email)
			if errors.Is(err, pgx.ErrNoRows) {
				proofErr = domain.ErrChallenge
				return nil
			}
			if err != nil {
				return err
			}
			if !userRow.Active || !userRow.EmailVerifiedAt.Valid {
				proofErr = domain.ErrChallenge
				return nil
			}
			if err = queries.SetPassword(ctx, db.SetPasswordParams{UserID: userRow.UserID, PasswordHash: encodedPasswordHash}); err != nil {
				return err
			}
			if err = queries.RevokeUser(ctx, userRow.UserID); err != nil {
				return err
			}
			user = domain.User{ID: userRow.UserID, Email: userRow.Email, Name: userRow.DisplayName, Active: true}
		}
		return queries.ConsumeChallenge(ctx, challengeID)
	})
	if err != nil {
		return domain.User{}, err
	}
	if proofErr != nil {
		return domain.User{}, proofErr
	}
	return user, nil
}
