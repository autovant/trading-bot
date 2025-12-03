#!/bin/bash
# Quick setup script for Zoomex trading bot

set -e

echo "=========================================="
echo "Zoomex Trading Bot - Quick Setup"
echo "=========================================="

# Check Python version
echo "Checking Python version..."
python3 --version || { echo "Error: Python 3 not found"; exit 1; }

# Create virtual environment if it doesn't exist
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

# Activate virtual environment
echo "Activating virtual environment..."
source venv/bin/activate

# Install dependencies
echo "Installing dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

# Create necessary directories
echo "Creating directories..."
mkdir -p logs
mkdir -p data
mkdir -p configs

# Copy example config if needed
if [ ! -f "configs/zoomex_example.yaml" ]; then
    echo "Error: configs/zoomex_example.yaml not found"
    echo "Please ensure the configuration file exists"
    exit 1
fi

# Check for .env file
if [ ! -f ".env" ]; then
    echo ""
    echo "⚠️  WARNING: .env file not found"
    echo "Please create a .env file with your API credentials"
    echo "You can copy .env.example as a template:"
    echo "  cp .env.example .env"
    echo ""
    read -p "Press Enter to continue or Ctrl+C to exit..."
fi

# Load environment variables
if [ -f ".env" ]; then
    echo "Loading environment variables..."
    export $(cat .env | grep -v '^#' | xargs)
fi

# Run validation
echo ""
echo "=========================================="
echo "Running setup validation..."
echo "=========================================="
python tools/validate_setup.py --config configs/zoomex_example.yaml --mode testnet

echo ""
echo "=========================================="
echo "Setup Complete!"
echo "=========================================="
echo ""
echo "Next steps:"
echo "1. Review and edit configs/zoomex_example.yaml"
echo "2. Set your API credentials in .env"
echo "3. Run validation: python tools/validate_setup.py"
echo "4. Start paper trading: python run_bot.py --mode paper --config configs/zoomex_example.yaml"
echo "5. Start testnet trading: python run_bot.py --mode testnet --config configs/zoomex_example.yaml"
echo ""
