package main

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"math"
	"math/rand"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/nats-io/nats.go"
	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promhttp"
)

// MarketData represents enriched tick data
type MarketData struct {
	Symbol       string    `json:"symbol"`
	BestBid      float64   `json:"best_bid"`
	BestAsk      float64   `json:"best_ask"`
	BidSize      float64   `json:"bid_size"`
	AskSize      float64   `json:"ask_size"`
	LastPrice    float64   `json:"last_price"`
	LastSide     string    `json:"last_side"`
	LastSize     float64   `json:"last_size"`
	FundingRate  float64   `json:"funding_rate"`
	Timestamp    time.Time `json:"timestamp"`
	OrderFlowImb float64   `json:"order_flow_imbalance"`
}

var (
	lastPrice  = 50000.0
	atrEstimate = 100.0
)

// Config holds the service configuration
type Config struct {
	NATSServers []string `json:"nats_servers"`

	Subject     string   `json:"subject"`
	AppMode     string   `json:"app_mode"`
}

var (
	tradingMode = prometheus.NewGaugeVec(
		prometheus.GaugeOpts{
			Name: "trading_mode",
			Help: "Current trading mode",
		},
		[]string{"mode"},
	)

	spreadAtrGauge = prometheus.NewGaugeVec(
		prometheus.GaugeOpts{
			Name: "market_spread_atr_percent",
			Help: "Simulated spread to ATR percentage",
		},
		[]string{"symbol"},
	)
)

func init() {
	prometheus.MustRegister(tradingMode, spreadAtrGauge)
}

func main() {
	// Load configuration
	appMode := os.Getenv("APP_MODE")
	if appMode == "" {
		appMode = "paper"
	}

	config := &Config{
		NATSServers: []string{"nats://localhost:4222"},
		Subject:     "market.data",
		AppMode:     appMode,
	}

	rand.Seed(time.Now().UnixNano())
	// Set the trading mode metric
	tradingMode.With(prometheus.Labels{"mode": config.AppMode}).Set(1)

	// Start Prometheus metrics server
	go func() {
		http.Handle("/metrics", promhttp.Handler())
		log.Fatal(http.ListenAndServe(":8081", nil))
	}()

	// Connect to NATS
	nc, err := nats.Connect(config.NATSServers[0])
	if err != nil {
		log.Fatalf("Failed to connect to NATS: %v", err)
	}
	defer nc.Close()

	log.Println("Feed handler connected to NATS")

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

	// Start feed handler
	if err := startFeedHandler(ctx, nc, config); err != nil {
		log.Fatalf("Feed handler error: %v", err)
	}

	log.Println("Feed handler stopped")
}

func startFeedHandler(ctx context.Context, nc *nats.Conn, config *Config) error {
	ticker := time.NewTicker(1 * time.Second)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			return nil
		case <-ticker.C:
			// Simulate fetching market data
			data := generateMockData()
			
			// Publish to NATS
			if err := publishMarketData(nc, config.Subject, data); err != nil {
				log.Printf("Error publishing market data: %v", err)
			}
		}
	}
}

func generateMockData() *MarketData {
	now := time.Now()
	if lastPrice <= 0 {
		lastPrice = 50000
	}
	drift := rand.NormFloat64() * 25
	price := math.Max(1000, lastPrice+drift)
	spread := math.Max(price*0.0004, 2)
	atrEstimate = atrEstimate*0.85 + spread*0.15
	bestBid := price - spread/2
	bestAsk := price + spread/2
	bidSize := 50 + rand.Float64()*50
	askSize := 50 + rand.Float64()*50
	lastSide := "buy"
	if price < lastPrice {
		lastSide = "sell"
	}
	lastQty := (bidSize + askSize) * 0.25
	funding := 0.0001 * math.Sin(float64(now.UnixNano()%int64(time.Hour))/float64(time.Hour)*2*math.Pi)
	ofi := (bidSize - askSize) * spread
	snapshot := &MarketData{
		Symbol:       "BTCUSDT",
		BestBid:      bestBid,
		BestAsk:      bestAsk,
		BidSize:      bidSize,
		AskSize:      askSize,
		LastPrice:    price,
		LastSide:     lastSide,
		LastSize:     lastQty,
		FundingRate:  funding,
		Timestamp:    now,
		OrderFlowImb: ofi,
	}
	spreadAtr := (spread / math.Max(atrEstimate, 1)) * 100
	spreadAtrGauge.WithLabelValues(snapshot.Symbol).Set(spreadAtr)

	lastPrice = price
	return snapshot
}

func publishMarketData(nc *nats.Conn, subject string, data *MarketData) error {
	payload, err := json.Marshal(data)
	if err != nil {
		return fmt.Errorf("failed to marshal data: %w", err)
	}

	if err := nc.Publish(subject, payload); err != nil {
		return fmt.Errorf("failed to publish to NATS: %w", err)
	}

	log.Printf("Published market data %s bid=%.2f ask=%.2f last=%.2f", data.Symbol, data.BestBid, data.BestAsk, data.LastPrice)
	return nil
}
