#!/bin/bash

# Start Docker containers
echo "🚀 Starting AI Job Assistant with Docker..."
echo ""

# Check if Docker is installed
if ! command -v docker &> /dev/null; then
    echo "❌ Docker is not installed. Please install Docker first."
    exit 1
fi

# Check if docker-compose is installed
if ! command -v docker-compose &> /dev/null; then
    echo "❌ docker-compose is not installed. Please install Docker Compose first."
    exit 1
fi

# Start services
docker-compose up

echo ""
echo "✅ Application started!"
echo ""
echo "Access points:"
echo "  API: http://localhost:8000"
echo "  API Docs: http://localhost:8000/docs"
echo "  Streamlit UI: http://localhost:8501"
echo ""
echo "To stop, press Ctrl+C"
