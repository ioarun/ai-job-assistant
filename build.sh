#!/bin/bash

# Build Docker images
echo "🐳 Building Docker images..."
docker-compose build

echo ""
echo "✅ Build complete!"
echo ""
echo "To start the application, run:"
echo "  docker-compose up"
echo ""
echo "Access points:"
echo "  API: http://localhost:8000"
echo "  API Docs: http://localhost:8000/docs"
echo "  Streamlit UI: http://localhost:8501"
echo ""
echo "To stop the application, run:"
echo "  docker-compose down"
