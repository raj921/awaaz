package apperror

import "fmt"

type AppError struct {
	Message    string `json:"message"`
	Code       string `json:"code"`
	StatusCode int    `json:"-"`
}

func (e *AppError) Error() string {
	return fmt.Sprintf("%s: %s", e.Code, e.Message)
}

func NewBadRequest(msg string) *AppError {
	return &AppError{
		Message:    msg,
		Code:       "BAD_REQUEST",
		StatusCode: 400,
	}
}

func NewUnprocessable(msg string) *AppError {
	return &AppError{
		Message:    msg,
		Code:       "VALIDATION_ERROR",
		StatusCode: 422,
	}
}

func NewBadGateway(msg string) *AppError {
	return &AppError{
		Message:    msg,
		Code:       "UPSTREAM_ERROR",
		StatusCode: 502,
	}
}

func NewGatewayTimeout(msg string) *AppError {
	return &AppError{
		Message:    msg,
		Code:       "UPSTREAM_TIMEOUT",
		StatusCode: 504,
	}
}

func NewServiceUnavailable(msg string) *AppError {
	return &AppError{
		Message:    msg,
		Code:       "SERVICE_UNAVAILABLE",
		StatusCode: 503,
	}
}

func NewTooManyRequests(msg string) *AppError {
	return &AppError{
		Message:    msg,
		Code:       "RATE_LIMITED",
		StatusCode: 429,
	}
}

func NewForbidden(msg string) *AppError {
	return &AppError{
		Message:    msg,
		Code:       "FORBIDDEN",
		StatusCode: 403,
	}
}
