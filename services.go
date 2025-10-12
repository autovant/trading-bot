package main

import (
	"context"
	"flag"
	"log"
	"os"
	"os/signal"
	"syscall"
)

func main() {
	// Parse command line flags
	service := flag.String("service", "", "Service to run (feed, execution, risk, reporter, ops)")
	flag.Parse()

	if *service == "" {
		log.Fatal("Please specify a service to run: -service=feed|execution|risk|reporter|ops")
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
	}()

	// Run the specified service
	switch *service {
	case "feed":
		if err := runFeedHandler(ctx); err != nil {
			log.Fatalf("Feed handler error: %v", err)
		}
	case "execution":
		if err := runExecutionService(ctx); err != nil {
			log.Fatalf("Execution service error: %v", err)
		}
	case "risk":
		if err := runRiskStateService(ctx); err != nil {
			log.Fatalf("Risk state service error: %v", err)
		}
	case "reporter":
		if err := runReporterService(ctx); err != nil {
			log.Fatalf("Reporter service error: %v", err)
		}
	case "ops":
		if err := runOpsAPIService(ctx); err != nil {
			log.Fatalf("Ops API service error: %v", err)
		}
	default:
		log.Fatalf("Unknown service: %s. Use feed, execution, risk, reporter, or ops", *service)
	}

	log.Println("Service stopped")
}

func runFeedHandler(ctx context.Context) error {
	log.Println("Starting Feed Handler Service")
	// Implementation would go here
	// For now, we'll just wait for context cancellation
	<-ctx.Done()
	return nil
}

func runExecutionService(ctx context.Context) error {
	log.Println("Starting Execution Service")
	// Implementation would go here
	// For now, we'll just wait for context cancellation
	<-ctx.Done()
	return nil
}

func runRiskStateService(ctx context.Context) error {
	log.Println("Starting Risk State Service")
	// Implementation would go here
	// For now, we'll just wait for context cancellation
	<-ctx.Done()
	return nil
}

func runReporterService(ctx context.Context) error {
	log.Println("Starting Reporter Service")
	// Implementation would go here
	// For now, we'll just wait for context cancellation
	<-ctx.Done()
	return nil
}

func runOpsAPIService(ctx context.Context) error {
	log.Println("Starting Ops API Service")
	// Implementation would go here
	// For now, we'll just wait for context cancellation
	<-ctx.Done()
	return nil
}