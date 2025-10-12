package main

import (
	"context"
	"math/rand"
	"encoding/json"
	"log"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/nats-io/nats.go"
	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promhttp"
)

// RiskState represents the current risk state
type RiskState struct {
	CrisisMode         bool    `json:"crisis_mode"`
	ConsecutiveLosses  int     `json:"consecutive_losses"`
	Drawdown           float64 `json:"drawdown"`
	Volatility         float64 `json:"volatility"`
	PositionSizeFactor float64 `json:"position_size_factor"`
	Timestamp          time.Time `json:"timestamp"`
}

// Config holds the service configuration
type Config struct {
	NATSServers    []string `json:"nats_servers"`
	RiskSub        string   `json:"risk_subject"`
	StatePub       string   `json:"state_subject"`
	AppMode        string   `json:"app_mode"`
}

var (
	tradingMode = prometheus.NewGaugeVec(
		prometheus.GaugeOpts{
			Name: "trading_mode",
			Help: "Current trading mode",
		},
		[]string{"mode"},
	)

	circuitBreakers = prometheus.NewCounterVec(
		prometheus.CounterOpts{
			Name: "risk_circuit_breakers_total",
			Help: "Total number of circuit breaker triggers",
		},
		[]string{"mode"},
	)
)

func init() {
	prometheus.MustRegister(tradingMode, circuitBreakers)
}

func main() {
	// Load configuration
	appMode := os.Getenv("APP_MODE")
	if appMode == "" {
		appMode = "paper"
	}

	config := &Config{
		NATSServers: []string{"nats://localhost:4222"},
		RiskSub:     "risk.management",
		StatePub:    "risk.state",
		AppMode:     appMode,
	}

	rand.Seed(time.Now().UnixNano())

	// Set the trading mode metric
	tradingMode.With(prometheus.Labels{"mode": config.AppMode}).Set(1)

	// Start Prometheus metrics server
	go func() {
		http.Handle("/metrics", promhttp.Handler())
		log.Fatal(http.ListenAndServe(":8084", nil))
	}()

	// Connect to NATS
	nc, err := nats.Connect(config.NATSServers[0])
	if err != nil {
		log.Fatalf("Failed to connect to NATS: %v", err)
	}
	defer nc.Close()

	log.Println("Risk state service connected to NATS")

	// Create context with cancel
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	// Handle shutdown signals
	sigChan := make(chan os.Signal, 1)
	signal.Notify(sigChan, syscall.SIGINT, syscall.SIGTERM)
	go func() {
		<-sigChan
		log.Println("Received shutdown signal")
		cancel()
	}()

	// Start risk state publisher
	if err := startRiskStatePublisher(ctx, nc, config); err != nil {
		log.Fatalf("Risk state service error: %v", err)
	}

	log.Println("Risk state service stopped")
}

func startRiskStatePublisher(ctx context.Context, nc *nats.Conn, config *Config) error {
	ticker := time.NewTicker(5 * time.Second)
	defer ticker.Stop()

	riskState := &RiskState{
		CrisisMode:         false,
		ConsecutiveLosses:  0,
		Drawdown:           0.0,
		Volatility:         0.0,
		PositionSizeFactor: 1.0,
	}

	for {
		select {
		case <-ctx.Done():
			return nil
		case <-ticker.C:
			riskState.Timestamp = time.Now()
			riskState.Volatility = rand.Float64()
			riskState.Drawdown = math.Abs(math.Sin(float64(time.Now().UnixNano()%int64(time.Hour)) / float64(time.Hour))) * 0.2
			riskState.PositionSizeFactor = 1 - rand.Float64()*0.3

			if rand.Float64() < 0.05 {
				riskState.CrisisMode = !riskState.CrisisMode
				if riskState.CrisisMode {
					riskState.ConsecutiveLosses++
					circuitBreakers.WithLabelValues(config.AppMode).Inc()
				}
			}

			if err := publishRiskState(nc, config.StatePub, riskState); err != nil {
				log.Printf("Error publishing risk state: %v", err)
			}
		}
	}
}

func publishRiskState(nc *nats.Conn, subject string, state *RiskState) error {
	payload, err := json.Marshal(state)
	if err != nil {
		return err
	}

	if err := nc.Publish(subject, payload); err != nil {
		return err
	}

	log.Printf("Published risk state: CrisisMode=%t, Drawdown=%.2f%%", state.CrisisMode, state.Drawdown*100)
	return nil
}
