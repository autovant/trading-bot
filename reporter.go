package main

import (
	"context"
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

// PerformanceReport represents strategy performance metrics
type PerformanceReport struct {
	TotalTrades    int     `json:"total_trades"`
	WinRate        float64 `json:"win_rate"`
	TotalPnL       float64 `json:"total_pnl"`
	MaxDrawdown    float64 `json:"max_drawdown"`
	SharpeRatio    float64 `json:"sharpe_ratio"`
	Timestamp      time.Time `json:"timestamp"`
}

// Config holds the service configuration
type Config struct {
	NATSServers    []string `json:"nats_servers"`
	PerfSub        string   `json:"performance_subject"`
	ReportPub      string   `json:"report_subject"`
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
		PerfSub:     "performance.metrics",
		ReportPub:   "reports.performance",
		AppMode:     appMode,
	}

	// Set the trading mode metric
	tradingMode.With(prometheus.Labels{"mode": config.AppMode}).Set(1)

	// Start Prometheus metrics server
	go func() {
		http.Handle("/metrics", promhttp.Handler())
		log.Fatal(http.ListenAndServe(":8083", nil))
	}()

	// Connect to NATS
	nc, err := nats.Connect(config.NATSServers[0])
	if err != nil {
		log.Fatalf("Failed to connect to NATS: %v", err)
	}
	defer nc.Close()

	log.Println("Reporter service connected to NATS")

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

	// Subscribe to performance metrics
	sub, err := nc.Subscribe(config.PerfSub, func(msg *nats.Msg) {
		// In a real implementation, this would process performance metrics
		log.Printf("Received performance metrics update")
	})
	if err != nil {
		log.Fatalf("Failed to subscribe to performance metrics: %v", err)
	}
	defer sub.Unsubscribe()

	log.Printf("Subscribed to performance metrics on subject: %s", config.PerfSub)

	// Start report generator
	if err := startReportGenerator(ctx, nc, config); err != nil {
		log.Fatalf("Reporter service error: %v", err)
	}

	log.Println("Reporter service stopped")
}

func startReportGenerator(ctx context.Context, nc *nats.Conn, config *Config) error {
	ticker := time.NewTicker(1 * time.Minute)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			return nil
		case <-ticker.C:
			// Generate and publish performance report
			report := generatePerformanceReport()
			if err := publishPerformanceReport(nc, config.ReportPub, report); err != nil {
				log.Printf("Error publishing performance report: %v", err)
			}
		}
	}
}

func generatePerformanceReport() *PerformanceReport {
	// In a real implementation, this would gather actual performance metrics
	return &PerformanceReport{
		TotalTrades: 10,
		WinRate:     0.6,
		TotalPnL:    150.0,
		MaxDrawdown: 0.05,
		SharpeRatio: 1.2,
		Timestamp:   time.Now(),
	}
}

func publishPerformanceReport(nc *nats.Conn, subject string, report *PerformanceReport) error {
	payload, err := json.Marshal(report)
	if err != nil {
		return err
	}

	if err := nc.Publish(subject, payload); err != nil {
		return err
	}

	log.Printf("Published performance report: Trades=%d, WinRate=%.2f, PnL=%.2f", 
		report.TotalTrades, report.WinRate, report.TotalPnL)
	return nil
}
