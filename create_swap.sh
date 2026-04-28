#!/bin/bash
# ─── Aurora Optimizer: Swap Space Creator ───────────────────────────────────
# Use this script to add 2GB of Swap space to your Linux VM. 
# Essential for running LLM agents on low-RAM (1GB) instances.
# ─────────────────────────────────────────────────────────────────────────────

echo "🚀 Allocating 2GB swap space..."
sudo fallocate -l 2G /swapfile

echo "🔒 Setting permissions..."
sudo chmod 600 /swapfile

echo "🛠️ Formatting swap..."
sudo mkswap /swapfile

echo "🔛 Activating swap..."
sudo swapon /swapfile

echo "💾 Making swap persistent (adding to /etc/fstab)..."
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab

echo "✅ Success! Current memory status:"
free -h
