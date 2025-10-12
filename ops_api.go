package main

import (
	"context"
	"fmt"
	"encoding/json"
	"log"
	"net/http"
	"os"
	"os/signal"
	"sync"
	"syscall"
	"time"

	"github.com/nats-io/nats.go"
	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promhttp"
)

// APIServer represents the ops API service
type APIServer struct {
	server *http.Server
	nc     *nats.Conn
	config *Config
	mu     sync.RWMutex
}

type LatencyConfig struct {
	Mean float64 `json:"mean"`
	P95  float64 `json:"p95"`
}

// PaperConfig holds the paper trading configuration
type PaperConfig struct {
	FeeBps         float64       `json:"fee_bps"`
	MakerRebateBps float64       `json:"maker_rebate_bps"`
	SlippageBps    float64       `json:"slippage_bps"`
	MaxSlippageBps float64       `json:"max_slippage_bps"`
	FundingEnabled bool          `json:"funding_enabled"`
	PriceSource    string        `json:"price_source"`
	SpreadCoeff    float64       `json:"spread_slippage_coeff"`
	OFICoeff       float64       `json:"ofi_slippage_coeff"`
	Latency        LatencyConfig `json:"latency_ms"`
	PartialFill    PartialFillConfig `json:"partial_fill"`
}

type PartialFillConfig struct {
	Enabled     bool    `json:"enabled"`
	MinSlicePct float64 `json:"min_slice_pct"`
	MaxSlices   int     `json:"max_slices"`
}

// Config holds the service configuration
type Config struct {
	NATSServers []string `json:"nats_servers"`
	HTTPPort    string   `json:"http_port"`
	AppMode     string   `json:"app_mode"`
	Paper       PaperConfig `json:"paper"`
}

// HealthResponse represents the health check response
type HealthResponse struct {
	Status    string    `json:"status"`
	Timestamp time.Time `json:"timestamp"`
}

// ModeResponse represents the mode response
type ModeResponse struct {
	Mode   string `json:"mode"`
	Shadow bool   `json:"shadow"`
}

var (
	tradingMode = prometheus.NewGaugeVec(
		prometheus.GaugeOpts{
			Name: "trading_mode",
			Help: "Current trading mode",
		},
		[]string{"mode"},
	)
)

func init() {
	prometheus.MustRegister(tradingMode)
}

func main() {
	// Load configuration
	appMode := os.Getenv("APP_MODE")
	if appMode == "" {
		appMode = "paper"
	}

	config := &Config{
		NATSServers: []string{"nats://localhost:4222"},
		HTTPPort:    ":8082",
		AppMode:     appMode,
		Paper: PaperConfig{
			FeeBps:         7,
			MakerRebateBps: -1,
			SlippageBps:    3,
			MaxSlippageBps: 10,
			FundingEnabled: true,
			PriceSource:    "live",
			SpreadCoeff:    0.5,
			OFICoeff:       0.35,
			Latency: LatencyConfig{
				Mean: 120,
				P95:  300,
			},
			PartialFill: PartialFillConfig{
				Enabled:     true,
				MinSlicePct: 0.15,
				MaxSlices:   4,
			},
		},
	}

	// Set the trading mode metric
	tradingMode.With(prometheus.Labels{"mode": config.AppMode}).Set(1)

	// Connect to NATS
	nc, err := nats.Connect(config.NATSServers[0])
	if err != nil {
		log.Fatalf("Failed to connect to NATS: %v", err)
	}
	defer nc.Close()

	log.Println("Ops API service connected to NATS")

	// Create HTTP server
	api := &APIServer{
		nc:     nc,
		config: config,
	}

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
		api.server.Shutdown(context.Background())
	}()

	// Start HTTP server
	if err := api.startServer(ctx); err != nil {
		log.Fatalf("Ops API service error: %v", err)
	}

	log.Println("Ops API service stopped")
}

func (api *APIServer) startServer(ctx context.Context) error {
	mux := http.NewServeMux()
	
	// Health check endpoint
	mux.HandleFunc("/health", api.healthHandler)
	
	// Metrics endpoint
	mux.Handle("/metrics", promhttp.Handler())
	
	// Mode endpoints
	mux.HandleFunc("/api/mode", api.modeHandler)

	// Paper config endpoints
	mux.HandleFunc("/api/paper/config", api.paperConfigHandler)

	// Start server
	api.server = &http.Server{
		Addr:    api.config.HTTPPort,
		Handler: mux,
	}
	
	log.Printf("Ops API server starting on %s", api.config.HTTPPort)
	
	// Start server in goroutine
	go func() {
		if err := api.server.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			log.Printf("HTTP server error: %v", err)
		}
	}()
	
	// Wait for context cancellation
	<-ctx.Done()
	
	// Shutdown server
	return api.server.Shutdown(context.Background())
}

func (api *APIServer) healthHandler(w http.ResponseWriter, r *http.Request) {
	response := HealthResponse{
		Status:    "healthy",
		Timestamp: time.Now(),
	}
	
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(response)
}

func (api *APIServer) modeHandler(w http.ResponseWriter, r *http.Request) {
	api.mu.Lock()
	defer api.mu.Unlock()

	switch r.Method {
	case http.MethodGet:
		response := ModeResponse{
			Mode:   api.config.AppMode,
			Shadow: false,
		}
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(response)
	case http.MethodPost:
		var req ModeResponse
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			http.Error(w, "invalid request body", http.StatusBadRequest)
			return
		}
		switch req.Mode {
		case "live", "paper", "replay":
		default:
			http.Error(w, "invalid mode", http.StatusBadRequest)
			return
		}

		if api.config.AppMode == "live" && req.Mode != "live" {
			http.Error(w, "mode change blocked while live risk active", http.StatusConflict)
			return
		}

		if req.Mode != api.config.AppMode {
			api.config.AppMode = req.Mode
			tradingMode.Reset()
			tradingMode.With(prometheus.Labels{"mode": api.config.AppMode}).Set(1)
		}

		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(ModeResponse{Mode: api.config.AppMode})
	default:
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
	}
}


func (api *APIServer) paperConfigHandler(w http.ResponseWriter, r *http.Request) {
	api.mu.Lock()
	defer api.mu.Unlock()

	switch r.Method {
	case http.MethodGet:
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(api.config.Paper)
	case http.MethodPost:
		var req PaperConfig
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			http.Error(w, "invalid request body", http.StatusBadRequest)
			return
		}
		if err := validatePaperConfig(req); err != nil {
			http.Error(w, err.Error(), http.StatusBadRequest)
			return
		}

		api.config.Paper = req
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(api.config.Paper)
	default:
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
	}
}

func validatePaperConfig(cfg PaperConfig) error {
	if cfg.PriceSource != "live" && cfg.PriceSource != "bars" && cfg.PriceSource != "replay" {
		return fmt.Errorf("invalid price_source")
	}
	if cfg.SlippageBps < 0 || cfg.MaxSlippageBps < cfg.SlippageBps {
		return fmt.Errorf("max_slippage_bps must be >= slippage_bps")
	}
	if cfg.Latency.Mean < 0 || cfg.Latency.P95 < cfg.Latency.Mean {
		return fmt.Errorf("latency_ms invalid")
	}
	if cfg.PartialFill.MaxSlices < 1 {
		return fmt.Errorf("partial_fill.max_slices must be >= 1")
	}
	if cfg.PartialFill.MinSlicePct < 0 || cfg.PartialFill.MinSlicePct > 1 {
		return fmt.Errorf("partial_fill.min_slice_pct must be between 0 and 1")
	}
	if cfg.SpreadCoeff < 0 || cfg.OFICoeff < 0 {
		return fmt.Errorf("slippage coefficients must be non-negative")
	}
	return nil
}
