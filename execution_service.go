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
	"sync"
	"syscall"
	"time"

	"github.com/nats-io/nats.go"
	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promhttp"
)

type OrderType string
type Side string

const (
	OrderTypeMarket     OrderType = "market"
	OrderTypeLimit      OrderType = "limit"
	OrderTypeStopMarket OrderType = "stop_market"

	SideBuy  Side = "buy"
	SideSell Side = "sell"
)

// Order represents an inbound intent from the strategy.
type Order struct {
	ID         string    `json:"id"`
	ClientID   string    `json:"client_id"`
	Symbol     string    `json:"symbol"`
	Type       string    `json:"type"`
	Side       string    `json:"side"`
	Price      float64   `json:"price"`
	StopPrice  float64   `json:"stop_price"`
	Quantity   float64   `json:"quantity"`
	ReduceOnly bool      `json:"reduce_only"`
	Timestamp  time.Time `json:"timestamp"`
	IsShadow   bool      `json:"is_shadow"`
}

// ExecutionReport is published back to the strategy.
type ExecutionReport struct {
	OrderID       string    `json:"order_id"`
	ClientID      string    `json:"client_id"`
	Symbol        string    `json:"symbol"`
	Executed      bool      `json:"executed"`
	Price         float64   `json:"price"`
	MarkPrice     float64   `json:"mark_price"`
	Quantity      float64   `json:"quantity"`
	Fees          float64   `json:"fees"`
	Funding       float64   `json:"funding"`
	RealizedPnL   float64   `json:"realized_pnl"`
	SlippageBps   float64   `json:"slippage_bps"`
	Maker         bool      `json:"maker"`
	LatencyMs     float64   `json:"latency_ms"`
	AckLatencyMs  float64   `json:"ack_latency_ms"`
	Mode          string    `json:"mode"`
	RunID         string    `json:"run_id"`
	Timestamp     time.Time `json:"timestamp"`
	IsShadow      bool      `json:"is_shadow"`
	Error         string    `json:"error,omitempty"`
	ReduceOnly    bool      `json:"reduce_only"`
	OrderType     string    `json:"order_type"`
	StopPrice     float64   `json:"stop_price,omitempty"`
	InitialPrice  float64   `json:"initial_price,omitempty"`
	InitialSymbol string    `json:"initial_symbol,omitempty"`
}

// MarketData represents snapshot information produced by feed or replay.
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

// Config for the execution service.
type Config struct {
	NATSServers   []string   `json:"nats_servers"`
	OrdersSubject string     `json:"orders_subject"`
	ExecSubject   string     `json:"execution_subject"`
	AppMode       string     `json:"app_mode"`
	RunID         string     `json:"run_id"`
	Paper         PaperConfig `json:"paper"`
}

// PaperConfig controls the paper broker simulation.
type PaperConfig struct {
	FeeBps           float64 `json:"fee_bps"`
	MakerRebateBps   float64 `json:"maker_rebate_bps"`
	FundingEnabled   bool    `json:"funding_enabled"`
	SlippageBps      float64 `json:"slippage_bps"`
	MaxSlippageBps   float64 `json:"max_slippage_bps"`
	SpreadCoeff      float64 `json:"spread_slippage_coeff"`
	OFICoeff         float64 `json:"ofi_slippage_coeff"`
	Seed             int64   `json:"seed"`
	Latency          LatencyConfig      `json:"latency_ms"`
	PartialFill      PartialFillConfig  `json:"partial_fill"`
}

type LatencyConfig struct {
	Mean float64 `json:"mean"`
	P95  float64 `json:"p95"`
}

type PartialFillConfig struct {
	Enabled     bool    `json:"enabled"`
	MinSlicePct float64 `json:"min_slice_pct"`
	MaxSlices   int     `json:"max_slices"`
}

type MarketState struct {
	BestBid     float64
	BestAsk     float64
	BidSize     float64
	AskSize     float64
	LastPrice   float64
	LastSide    string
	LastSize    float64
	FundingRate float64
	OrderFlow   float64
	Timestamp   time.Time
}

type PositionState struct {
	Size      float64
	AvgPrice  float64
	MarkPrice float64
	UnrealPnL float64
}

type PaperBroker struct {
	mu            sync.Mutex
	config        PaperConfig
	nc            *nats.Conn
	execSubject   string
	runID         string
	mode          string
	latencySigma  float64
	random        *rand.Rand
	market        map[string]*MarketState
	positions     map[string]*PositionState
	makerCount    float64
	takerCount    float64
}

var (
	tradingMode = prometheus.NewGaugeVec(
		prometheus.GaugeOpts{
			Name: "trading_mode",
			Help: "Current trading mode",
		},
		[]string{"mode"},
	)

	signalAckLatency = prometheus.NewHistogramVec(
		prometheus.HistogramOpts{
			Name:    "signal_ack_latency_seconds",
			Help:    "Latency between order intent and simulated acknowledgement",
			Buckets: prometheus.DefBuckets,
		},
		[]string{"mode"},
	)

	fillLatency = prometheus.NewHistogramVec(
		prometheus.HistogramOpts{
			Name:    "paper_fill_latency_seconds",
			Help:    "Latency between order ack and fill in paper broker",
			Buckets: prometheus.DefBuckets,
		},
		[]string{"mode"},
	)

	slippageHistogram = prometheus.NewHistogramVec(
		prometheus.HistogramOpts{
			Name:    "paper_slippage_bps",
			Help:    "Observed slippage in basis points",
			Buckets: []float64{0.0, 1.0, 2.5, 5, 7.5, 10, 15, 20},
		},
		[]string{"mode"},
	)

	makerRatio = prometheus.NewGaugeVec(
		prometheus.GaugeOpts{
			Name: "paper_maker_ratio",
			Help: "Ratio of maker fills recorded by paper broker",
		},
		[]string{"mode"},
	)

	rejectCounter = prometheus.NewCounterVec(
		prometheus.CounterOpts{
			Name: "paper_order_rejects_total",
			Help: "Total number of rejected orders",
		},
		[]string{"mode"},
	)
)

func init() {
	prometheus.MustRegister(tradingMode, signalAckLatency, fillLatency, slippageHistogram, makerRatio, rejectCounter)
}

func main() {
	appMode := getenv("APP_MODE", "paper")
	runID := os.Getenv("RUN_ID")
	if runID == "" {
		runID = fmt.Sprintf("%s-%d", appMode, time.Now().Unix())
	}

	config := &Config{
		NATSServers:   []string{getenv("NATS_URL", "nats://localhost:4222")},
		OrdersSubject: getenv("ORDERS_SUBJECT", "trading.orders"),
		ExecSubject:   getenv("EXEC_SUBJECT", "trading.executions"),
		AppMode:       appMode,
		RunID:         runID,
		Paper: PaperConfig{
			FeeBps:         7,
			MakerRebateBps: -1,
			FundingEnabled: true,
			SlippageBps:    3,
			MaxSlippageBps: 10,
			SpreadCoeff:    0.5,
			OFICoeff:       0.35,
			Seed:           time.Now().UnixNano(),
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

	tradingMode.With(prometheus.Labels{"mode": appMode}).Set(1)

	go func() {
		httpAddr := getenv("METRICS_ADDR", ":8080")
		http.Handle("/metrics", promhttp.Handler())
		log.Printf("Prometheus metrics exposed on %s", httpAddr)
		if err := http.ListenAndServe(httpAddr, nil); err != nil {
			log.Printf("metrics server error: %v", err)
		}
	}()

	nc, err := nats.Connect(config.NATSServers[0])
	if err != nil {
		log.Fatalf("failed to connect to NATS: %v", err)
	}
	defer nc.Close()

	log.Printf("Execution service connected to NATS at %s (mode=%s)", config.NATSServers[0], appMode)

	broker := NewPaperBroker(config.Paper, nc, config.ExecSubject, config.RunID, config.AppMode)

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	sigChan := make(chan os.Signal, 1)
	signal.Notify(sigChan, syscall.SIGINT, syscall.SIGTERM)
	go func() {
		<-sigChan
		log.Println("Execution service shutting down")
		cancel()
	}()

	_, err = nc.Subscribe(getenv("MARKET_DATA_SUBJECT", "market.data"), func(msg *nats.Msg) {
		var snapshot MarketData
		if err := json.Unmarshal(msg.Data, &snapshot); err != nil {
			log.Printf("could not unmarshal market data: %v", err)
			return
		}
		broker.UpdateMarket(snapshot)
	})
	if err != nil {
		log.Fatalf("failed to subscribe to market data: %v", err)
	}

	_, err = nc.Subscribe(config.OrdersSubject, func(msg *nats.Msg) {
		var order Order
		if err := json.Unmarshal(msg.Data, &order); err != nil {
			log.Printf("could not parse order message: %v", err)
			return
		}
		if order.ClientID == "" {
			order.ClientID = order.ID
		}
		if order.Timestamp.IsZero() {
			order.Timestamp = time.Now()
		}

		switch config.AppMode {
		case "paper", "replay":
			log.Printf("Simulating order %s %s %s qty=%.4f", order.ClientID, order.Type, order.Symbol, order.Quantity)
			broker.HandleOrder(order)
		case "live":
			rejectCounter.WithLabelValues(config.AppMode).Inc()
			log.Printf("Live mode order received %s but live execution not implemented; rejecting", order.ClientID)
			report := ExecutionReport{
				OrderID:      order.ID,
				ClientID:     order.ClientID,
				Symbol:       order.Symbol,
				Executed:     false,
				Error:        "live execution not configured",
				Mode:         config.AppMode,
				RunID:        config.RunID,
				Timestamp:    time.Now(),
				OrderType:    order.Type,
				ReduceOnly:   order.ReduceOnly,
				StopPrice:    order.StopPrice,
				InitialPrice: order.Price,
			}
			payload, _ := json.Marshal(report)
			if err := nc.Publish(config.ExecSubject, payload); err != nil {
				log.Printf("failed to publish rejection: %v", err)
			}
		default:
			log.Printf("Unknown APP_MODE %s", config.AppMode)
		}
	})
	if err != nil {
		log.Fatalf("failed to subscribe to orders subject: %v", err)
	}

	<-ctx.Done()
	log.Println("Execution service stopped")
}

func getenv(key, fallback string) string {
	value := os.Getenv(key)
	if value == "" {
		return fallback
	}
	return value
}

func NewPaperBroker(cfg PaperConfig, nc *nats.Conn, execSubject, runID, mode string) *PaperBroker {
	sigma := deriveSigma(cfg.Latency.Mean, cfg.Latency.P95)
	seed := cfg.Seed
	if seed == 0 {
		seed = time.Now().UnixNano()
	}
	return &PaperBroker{
		config:       cfg,
		nc:           nc,
		execSubject:  execSubject,
		runID:        runID,
		mode:         mode,
		latencySigma: sigma,
		random:       rand.New(rand.NewSource(seed)),
		market:       make(map[string]*MarketState),
		positions:    make(map[string]*PositionState),
	}
}

func deriveSigma(mean, p95 float64) float64 {
	if p95 <= mean {
		if mean > 0 {
			return mean * 0.2
		}
		return 1.0
	}
	return math.Max((p95-mean)/1.645, 1.0)
}

func (pb *PaperBroker) UpdateMarket(snapshot MarketData) {
	pb.mu.Lock()
	defer pb.mu.Unlock()

	state, ok := pb.market[snapshot.Symbol]
	if !ok {
		state = &MarketState{}
		pb.market[snapshot.Symbol] = state
	}

	state.BestBid = snapshot.BestBid
	state.BestAsk = snapshot.BestAsk
	state.BidSize = snapshot.BidSize
	state.AskSize = snapshot.AskSize
	state.LastPrice = snapshot.LastPrice
	state.LastSide = snapshot.LastSide
	state.LastSize = snapshot.LastSize
	state.FundingRate = snapshot.FundingRate
	state.Timestamp = snapshot.Timestamp
	if len(snapshot.LastSide) > 0 {
		imbalance := snapshot.LastSize
		if snapshot.LastSide == "sell" {
			imbalance = -math.Abs(snapshot.LastSize)
		}
		state.OrderFlow = state.OrderFlow*0.85 + imbalance
	}

	position, ok := pb.positions[snapshot.Symbol]
	if ok && position.Size != 0 {
		mid := (state.BestBid + state.BestAsk) / 2
		if mid <= 0 {
			mid = state.LastPrice
		}
		position.MarkPrice = mid
		sign := 1.0
		if position.Size < 0 {
			sign = -1.0
		}
		position.UnrealPnL = (mid - position.AvgPrice) * position.Size * sign
	}
}

func (pb *PaperBroker) HandleOrder(order Order) {
	pb.mu.Lock()
	state, ok := pb.market[order.Symbol]
	pb.mu.Unlock()
	if !ok {
		log.Printf("No market state for %s; cannot execute paper order", order.Symbol)
		return
	}

	side := Side(order.Side)
	if side != SideBuy && side != SideSell {
		log.Printf("Unknown side %s", order.Side)
		return
	}

	orderType := OrderType(order.Type)
	if orderType != OrderTypeMarket && orderType != OrderTypeLimit && orderType != OrderTypeStopMarket {
		log.Printf("Unsupported order type %s", order.Type)
		return
	}

	maker := false
	cross := pb.limitCrossesSpread(orderType, side, order.Price, state)
	if orderType == OrderTypeLimit && !cross {
		maker = true
	}

	fillPlan := pb.buildFillPlan(orderType, side, order.Price, order.StopPrice, order.Quantity, state, maker)
	for _, fill := range fillPlan {
		go pb.completeFill(order, fill, maker)
	}
}

type fillSlice struct {
	delayMs      float64
	quantity     float64
	price        float64
	slipBps      float64
	markPrice    float64
	ackLatencyMs float64
}

func (pb *PaperBroker) limitCrossesSpread(orderType OrderType, side Side, price float64, state *MarketState) bool {
	mid := (state.BestBid + state.BestAsk) / 2
	switch orderType {
	case OrderTypeMarket:
		return true
	case OrderTypeLimit:
		if side == SideBuy {
			if state.BestAsk > 0 && price >= state.BestAsk {
				return true
			}
			return price >= mid
		}
		if state.BestBid > 0 && price <= state.BestBid {
			return true
		}
		return price <= mid
	default:
		return false
	}
}

func (pb *PaperBroker) buildFillPlan(orderType OrderType, side Side, price, stopPrice, quantity float64, state *MarketState, maker bool) []fillSlice {
	var slices []fillSlice
	mid := (state.BestBid + state.BestAsk) / 2
	if mid <= 0 {
		mid = state.LastPrice
	}
	if mid <= 0 {
		mid = price
	}
	ackLatency := pb.sampleLatency()

	switch orderType {
	case OrderTypeMarket, OrderTypeStopMarket:
		slippage := pb.computeSlippage(side, state)
		fillPrice := pb.applySlippage(side, mid, state, slippage)
		slices = append(slices, fillSlice{
			delayMs:      ackLatency,
			quantity:     quantity,
			price:        fillPrice,
			slipBps:      slippage,
			markPrice:    mid,
			ackLatencyMs: ackLatency,
		})
	case OrderTypeLimit:
		slippage := 0.0
		fillPrice := price
		if !maker {
			slippage = pb.computeSlippage(side, state)
			fillPrice = pb.applySlippage(side, mid, state, slippage)
		}
		if maker && pb.config.PartialFill.Enabled && pb.config.PartialFill.MaxSlices > 1 {
			numSlices := pb.random.Intn(pb.config.PartialFill.MaxSlices-1) + 1
			if numSlices < 1 {
				numSlices = 1
			}
			remaining := quantity
			for i := 0; i < numSlices; i++ {
				minPct := pb.config.PartialFill.MinSlicePct
				if minPct <= 0 {
					minPct = 0.05
				}
				minQty := quantity * minPct
				if minQty <= 0 {
					minQty = quantity / float64(numSlices)
				}
				if minQty > remaining {
					minQty = remaining
				}
				var sliceQty float64
				if i == numSlices-1 {
					sliceQty = remaining
				} else {
					maxAlloc := remaining - minQty*float64(numSlices-i-1)
					if maxAlloc <= minQty {
						sliceQty = minQty
					} else {
						sliceQty = minQty + pb.random.Float64()*(maxAlloc-minQty)
					}
				}
				if sliceQty <= 0 {
					continue
				}
				delay := pb.sampleLatency() * (1 + float64(i)*0.5)
				slices = append(slices, fillSlice{
					delayMs:      delay,
					quantity:     sliceQty,
					price:        fillPrice,
					slipBps:      0,
					markPrice:    mid,
					ackLatencyMs: ackLatency,
				})
		}
	}
	return slices
}

func (pb *PaperBroker) completeFill(order Order, fill fillSlice, maker bool) {
	time.Sleep(time.Duration(fill.delayMs) * time.Millisecond)

	pb.mu.Lock()
	defer pb.mu.Unlock()

	state, ok := pb.market[order.Symbol]
	if !ok {
		log.Printf("No market state for %s during fill", order.Symbol)
		return
	}
	position := pb.positions[order.Symbol]
	if position == nil {
		position = &PositionState{}
		pb.positions[order.Symbol] = position
	}

	realized, size, avg := applyPositionFill(position, Side(order.Side), fill.quantity, fill.price)
	position.Size = size
	position.AvgPrice = avg
	position.MarkPrice = fill.markPrice
	position.UnrealPnL = computeUnrealPnL(position)

	feeRate := pb.config.FeeBps / 10_000
	if maker {
		feeRate = pb.config.MakerRebateBps / 10_000
	}
	fees := fill.price * fill.quantity * feeRate
	funding := 0.0
	if pb.config.FundingEnabled {
		funding = fill.price * fill.quantity * state.FundingRate
	}
	netPnL := realized - fees - funding

	if maker {
		pb.makerCount++
	} else {
		pb.takerCount++
	}
	total := pb.makerCount + pb.takerCount
	if total > 0 {
		makerRatio.WithLabelValues(pb.mode).Set(pb.makerCount / total)
	}

	slippageHistogram.WithLabelValues(pb.mode).Observe(fill.slipBps)
	fillLatency.WithLabelValues(pb.mode).Observe(fill.delayMs / 1000.0)
	signalAckLatency.WithLabelValues(pb.mode).Observe(fill.ackLatencyMs / 1000.0)

	report := ExecutionReport{
		OrderID:      order.ID,
		ClientID:     order.ClientID,
		Symbol:       order.Symbol,
		Executed:     true,
		Price:        fill.price,
		MarkPrice:    fill.markPrice,
		Quantity:     fill.quantity,
		Fees:         fees,
		Funding:      funding,
		RealizedPnL:  realized,
		SlippageBps:  fill.slipBps,
		Maker:        maker,
		LatencyMs:    fill.delayMs,
		AckLatencyMs: fill.ackLatencyMs,
		Mode:         pb.mode,
		RunID:        pb.runID,
		Timestamp:    time.Now(),
		IsShadow:     order.IsShadow,
		ReduceOnly:   order.ReduceOnly,
		OrderType:    order.Type,
		StopPrice:    order.StopPrice,
		InitialPrice: order.Price,
		InitialSymbol: order.Symbol,
	}

	payload, err := json.Marshal(report)
	if err != nil {
		log.Printf("failed to marshal execution report: %v", err)
		return
	}
	if err := pb.nc.Publish(pb.execSubject, payload); err != nil {
		log.Printf("failed to publish execution report: %v", err)
	}
}

func applyPositionFill(position *PositionState, side Side, quantity, price float64) (float64, float64, float64) {
	size := position.Size
	avg := position.AvgPrice
	realized := 0.0
	sign := 1.0
	if side == SideSell {
		sign = -1.0
	}

	if size == 0 || size*sign >= 0 {
		newSize := size + quantity*sign
		totalQty := math.Abs(size) + quantity
		if totalQty <= 0 {
			return realized, newSize, price
		}
		newAvg := (avg*math.Abs(size) + price*quantity) / totalQty
		return realized, newSize, newAvg
	}

	closing := math.Min(math.Abs(size), quantity)
	if size > 0 {
		realized += (price - avg) * closing
	} else {
		realized += (avg - price) * closing
	}

	remaining := math.Abs(size) - closing
	if remaining > 0 {
		newSize := math.Copysign(remaining, size)
		return realized, newSize, avg
	}

	leftover := quantity - closing
	if leftover > 0 {
		newSize := leftover * sign
		return realized, newSize, price
	}
	return realized, 0, 0
}

func computeUnrealPnL(position *PositionState) float64 {
	if position.Size == 0 {
		return 0
	}
	mid := position.MarkPrice
	if mid <= 0 {
		return 0
	}
	sign := 1.0
	if position.Size < 0 {
		sign = -1.0
	}
	return (mid - position.AvgPrice) * position.Size * sign
}

func (pb *PaperBroker) computeSlippage(side Side, state *MarketState) float64 {
	spreadBps := 0.0
	mid := (state.BestBid + state.BestAsk) / 2
	if mid > 0 {
		spreadBps = (state.BestAsk - state.BestBid) / mid * 10_000
	}
	ofi := state.OrderFlow
	adverse := math.Max(0, ofi)
	if side == SideBuy {
		adverse = math.Max(0, -ofi)
	}
	slippage := pb.config.SlippageBps + spreadBps*pb.config.SpreadCoeff + adverse*pb.config.OFICoeff
	if slippage > pb.config.MaxSlippageBps {
		return pb.config.MaxSlippageBps
	}
	if slippage < 0 {
		return 0
	}
	return slippage
}

func (pb *PaperBroker) applySlippage(side Side, mid float64, state *MarketState, slippageBps float64) float64 {
	base := mid
	if side == SideBuy {
		if state.BestAsk > 0 {
			base = state.BestAsk
		}
		return base * (1 + slippageBps/10_000)
	}
	if state.BestBid > 0 {
		base = state.BestBid
	}
	return base * (1 - slippageBps/10_000)
}

func (pb *PaperBroker) sampleLatency() float64 {
	lat := pb.random.NormFloat64()*pb.latencySigma + pb.config.Latency.Mean
	if lat < 0 {
		return 0
	}
	return lat
}
