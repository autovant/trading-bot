package main

import (
	"context"
	"encoding/json"
	"testing"
	"time"

	"github.com/nats-io/nats.go"
)

func TestPaperBroker_MarketOrder(t *testing.T) {
	// Config
	config := &Config{
		AppMode: "paper",
		Paper: PaperConfig{
			FeeBps: 7,
		},
	}

	// NATS mock
	nc, _ := nats.Connect(nats.DefaultURL)

	// Paper broker
	paperBroker := NewPaperBroker(config, nc)
	paperBroker.lastPrice["BTCUSDT"] = 50000.0

	// Order
	order := &Order{
		ID:       "test-order",
		Symbol:   "BTCUSDT",
		Type:     "market",
		Side:     "buy",
		Quantity: 1.0,
	}

	// Execute
	report := paperBroker.executeOrder(order)

	// Assertions
	if !report.Executed {
		t.Error("Expected order to be executed")
	}

	if report.Price == 0 {
		t.Error("Expected execution price to be set")
	}

	if report.Commission == 0 {
		t.Error("Expected commission to be calculated")
	}

	if paperBroker.positions["BTCUSDT"] != 1.0 {
		t.Errorf("Expected position to be 1.0, got %.2f", paperBroker.positions["BTCUSDT"])
	}
}
