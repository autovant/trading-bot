package main

import (
	"context"
	"encoding/csv"
	"encoding/json"
	"fmt"
	"log"
	"math"
	"os"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/nats-io/nats.go"
	"github.com/xitongsys/parquet-go-source/local"
	"github.com/xitongsys/parquet-go/reader"
)

// MarketData represents market data for a symbol
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

// ReplayConfig holds the replay configuration
type ReplayConfig struct {
	Source string `json:"source"`
	Speed  string `json:"speed"`
	Start  string `json:"start"`
	End    string `json:"end"`
	ControlSubject string `json:"control_subject"`
}


type replayCommand struct {
	Command   string `json:"command"`
	Timestamp string `json:"timestamp"`
}
// Config holds the service configuration
type Config struct {
	NATSServers []string `json:"nats_servers"`
	MarketDataPub string   `json:"market_data_subject"`
	Replay      ReplayConfig `json:"replay"`
}

func main() {
	// Load configuration
	config := &Config{
		NATSServers: []string{"nats://localhost:4222"},
		MarketDataPub: "market.data",
		Replay: ReplayConfig{
			Source:         "sample_data/btc_eth_4h.parquet",
			Speed:          "10x",
			Start:          "2023-01-01",
			End:            "2024-12-31",
			ControlSubject: "replay.control",
		},
	}

	// Connect to NATS
	nc, err := nats.Connect(config.NATSServers[0])
	if err != nil {
		log.Fatalf("Failed to connect to NATS: %v", err)
	}
	defer nc.Close()

	log.Println("Replay service connected to NATS")

	// Create context with cancel
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	// Start replayer
	if err := startReplayer(ctx, nc, config); err != nil {
		log.Fatalf("Replay service error: %v", err)
	}

	log.Println("Replay service stopped")
}

func startReplayer(ctx context.Context, nc *nats.Conn, config *Config) error {
	data, err := readData(config.Replay.Source)
	if err != nil {
		return err
	}

	var startTime, endTime time.Time
	if config.Replay.Start != "" {
		if startTime, err = time.Parse(time.RFC3339, config.Replay.Start); err != nil {
			log.Printf("invalid replay start %q: %v", config.Replay.Start, err)
			startTime = time.Time{}
		}
	}
	if config.Replay.End != "" {
		if endTime, err = time.Parse(time.RFC3339, config.Replay.End); err != nil {
			log.Printf("invalid replay end %q: %v", config.Replay.End, err)
			endTime = time.Time{}
		}
	}

	if !startTime.IsZero() || !endTime.IsZero() {
		var filtered []MarketData
		for _, record := range data {
			if !startTime.IsZero() && record.Timestamp.Before(startTime) {
				continue
			}
			if !endTime.IsZero() && record.Timestamp.After(endTime) {
				continue
			}
			filtered = append(filtered, record)
		}
		if len(filtered) > 0 {
			data = filtered
		}
	}

	sort.Slice(data, func(i, j int) bool {
		return data[i].Timestamp.Before(data[j].Timestamp)
	})

	if len(data) == 0 {
		return fmt.Errorf("no replay data available for %s", config.Replay.Source)
	}

	speedStr := strings.TrimSuffix(strings.ToLower(config.Replay.Speed), "x")
	speed, err := strconv.Atoi(speedStr)
	if err != nil || speed <= 0 {
		log.Printf("invalid replay speed %s, defaulting to 1x", config.Replay.Speed)
		speed = 1
	}

	ticker := time.NewTicker(time.Second / time.Duration(speed))
	defer ticker.Stop()

	controlCh := make(chan replayCommand, 16)
	if config.Replay.ControlSubject != "" {
		if _, err := nc.Subscribe(config.Replay.ControlSubject, func(msg *nats.Msg) {
			var cmd replayCommand
			if err := json.Unmarshal(msg.Data, &cmd); err != nil {
				log.Printf("invalid replay control message: %v", err)
				return
			}
			select {
			case controlCh <- cmd:
			default:
				log.Printf("control channel saturated, dropping command %s", cmd.Command)
			}
		}); err != nil {
			return err
		}
	}

	paused := false
	index := 0

	for index < len(data) {
		select {
		case <-ctx.Done():
			return nil
		case cmd := <-controlCh:
			switch strings.ToLower(cmd.Command) {
			case "pause":
				paused = true
			case "resume":
				paused = false
			case "seek":
				if ts, err := time.Parse(time.RFC3339, cmd.Timestamp); err == nil {
					idx := seekIndex(data, ts)
					if idx >= 0 {
						index = idx
					}
				} else {
					log.Printf("invalid seek timestamp: %v", err)
				}
			default:
				log.Printf("unknown replay command: %s", cmd.Command)
			}
		case <-ticker.C:
			if paused {
				continue
			}
			record := data[index]
			if err := publishMarketData(nc, config.MarketDataPub, &record); err != nil {
				log.Printf("Error publishing market data: %v", err)
			}
			index++
		}
	}

	return nil
}


func readData(source string) ([]MarketData, error) {
	source = strings.TrimSpace(source)
	scheme, path := parseSource(source)

	switch scheme {
	case "csv":
		return readCSV(path)
	case "parquet":
		return readParquet(path)
	case "":
		if strings.HasSuffix(strings.ToLower(path), ".csv") {
			return readCSV(path)
		}
		if strings.HasSuffix(strings.ToLower(path), ".parquet") {
			return readParquet(path)
		}
	}

	return nil, fmt.Errorf("unsupported replay source: %s", source)
}

func readCSV(path string) ([]MarketData, error) {
	file, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer file.Close()

	reader := csv.NewReader(file)
	records, err := reader.ReadAll()
	if err != nil {
		return nil, err
	}
	if len(records) < 2 {
		return nil, fmt.Errorf("csv file %s has no data rows", path)
	}

	header := make(map[string]int)
	for idx, col := range records[0] {
		header[strings.ToLower(strings.TrimSpace(col))] = idx
	}

	required := []string{"timestamp", "open", "high", "low", "close"}
	for _, key := range required {
		if _, ok := header[key]; !ok {
			return nil, fmt.Errorf("csv file %s missing required column %q", path, key)
		}
	}

	symbolIdx, hasSymbol := header["symbol"]
	volumeIdx, hasVolume := header["volume"]

	var data []MarketData
	for _, record := range records[1:] {
		ts, err := time.Parse(time.RFC3339, record[header["timestamp"]])
		if err != nil {
			return nil, fmt.Errorf("invalid timestamp %q: %w", record[header["timestamp"]], err)
		}

		openVal, err := strconv.ParseFloat(record[header["open"]], 64)
		if err != nil {
			return nil, fmt.Errorf("invalid open price %q: %w", record[header["open"]], err)
		}
		highVal, err := strconv.ParseFloat(record[header["high"]], 64)
		if err != nil {
			return nil, fmt.Errorf("invalid high price %q: %w", record[header["high"]], err)
		}
		lowVal, err := strconv.ParseFloat(record[header["low"]], 64)
		if err != nil {
			return nil, fmt.Errorf("invalid low price %q: %w", record[header["low"]], err)
		}
		closeVal, err := strconv.ParseFloat(record[header["close"]], 64)
		if err != nil {
			return nil, fmt.Errorf("invalid close price %q: %w", record[header["close"]], err)
		}

		volume := 0.0
		if hasVolume && volumeIdx < len(record) && record[volumeIdx] != "" {
			if volume, err = strconv.ParseFloat(record[volumeIdx], 64); err != nil {
				volume = 0.0
			}
		}

		symbol := "BTCUSDT"
		if hasSymbol && symbolIdx < len(record) && record[symbolIdx] != "" {
			symbol = record[symbolIdx]
		}

		data = append(data, buildMarketData(symbol, ts, openVal, highVal, lowVal, closeVal, volume))
	}

	return data, nil
}

func readParquet(path string) ([]MarketData, error) {
	fr, err := local.NewLocalFileReader(path)
	if err != nil {
		return nil, err
	}
	defer fr.Close()

	type parquetRow struct {
		Timestamp int64   `parquet:"name=timestamp"`
		Symbol    string  `parquet:"name=symbol"`
		Open      float64 `parquet:"name=open"`
		High      float64 `parquet:"name=high"`
		Low       float64 `parquet:"name=low"`
		Close     float64 `parquet:"name=close"`
		Volume    float64 `parquet:"name=volume"`
	}

	pr, err := reader.NewParquetReader(fr, new(parquetRow), 4)
	if err != nil {
		return nil, err
	}
	defer pr.ReadStop()

	numRows := int(pr.GetNumRows())
	rows := make([]parquetRow, numRows)
	if err := pr.Read(&rows); err != nil {
		return nil, err
	}

	var data []MarketData
	for _, row := range rows {
		var ts time.Time
		switch {
		case row.Timestamp > 1e16:
			// nanoseconds since epoch
			ts = time.Unix(0, row.Timestamp).UTC()
		case row.Timestamp > 1e12:
			// milliseconds since epoch
			ts = time.Unix(0, row.Timestamp*int64(time.Millisecond)).UTC()
		case row.Timestamp > 1e9:
			// seconds since epoch
			ts = time.Unix(row.Timestamp, 0).UTC()
		default:
			ts = time.Unix(row.Timestamp, 0).UTC()
		}
		if row.Symbol == "" {
			row.Symbol = "BTCUSDT"
		}
		data = append(data, buildMarketData(row.Symbol, ts, row.Open, row.High, row.Low, row.Close, row.Volume))
	}

	return data, nil
}

func parseSource(source string) (scheme string, path string) {
	if idx := strings.Index(source, "://"); idx != -1 {
		return strings.ToLower(source[:idx]), source[idx+3:]
	}
	return "", source
}

func buildMarketData(symbol string, ts time.Time, open, high, low, close, volume float64) MarketData {
	volume = math.Max(volume, 1)
	ts = ts.UTC()
	spread := math.Max((high-low)*0.2, math.Max(close*0.0004, 0.5))
	bestBid := close - spread/2
	bestAsk := close + spread/2
	bidSize := math.Max(volume*0.25, 1)
	askSize := math.Max(volume*0.25, 1)
	side := "buy"
	if close < open {
		side = "sell"
	}
	lastSize := math.Max(volume*0.1, 1)
	ofi := (bidSize - askSize) * spread

	return MarketData{
		Symbol:       symbol,
		BestBid:      bestBid,
		BestAsk:      bestAsk,
		BidSize:      bidSize,
		AskSize:      askSize,
		LastPrice:    close,
		LastSide:     side,
		LastSize:     lastSize,
		FundingRate:  0,
		Timestamp:    ts,
		OrderFlowImb: ofi,
	}
}

func publishMarketData(nc *nats.Conn, subject string, data *MarketData) error {
	payload, err := json.Marshal(data)
	if err != nil {
		return fmt.Errorf("failed to marshal data: %w", err)
	}

	if err := nc.Publish(subject, payload); err != nil {
		return fmt.Errorf("failed to publish to NATS: %w", err)
	}

	log.Printf("Replay market data %s bid=%.2f ask=%.2f last=%.2f", data.Symbol, data.BestBid, data.BestAsk, data.LastPrice)
	return nil
}
func seekIndex(data []MarketData, target time.Time) int {
	for i, record := range data {
		if !record.Timestamp.Before(target) {
			return i
		}
	}
	if len(data) == 0 {
		return 0
	}
	return len(data) - 1
}
