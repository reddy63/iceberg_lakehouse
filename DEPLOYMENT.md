# 🚀 Deployment Guide — Iceberg Lakehouse on EC2

This document covers **production deployment** to an AWS EC2 instance via the
GitHub Actions CI/CD pipeline defined in `.github/workflows/deploy.yml`.

---

## Required GitHub Secrets

Go to your repository → **Settings → Secrets and variables → Actions** and add
the following three secrets:

| Secret name | Description | How to get it |
|---|---|---|
| `EC2_SSH_KEY` | Private SSH key (PEM format) that has access to your EC2 instance | Copy the full content of `~/.ssh/your-key.pem` |
| `EC2_HOST` | Public IPv4 address or DNS hostname of your EC2 instance | EC2 console → Instance summary → Public IPv4 |
| `EC2_USER` | SSH username on the instance | `ubuntu` for Ubuntu AMIs, `ec2-user` for Amazon Linux |

### Adding a secret (step by step)
1. Navigate to your GitHub repo
2. Click **Settings** → **Secrets and variables** → **Actions**
3. Click **New repository secret**
4. Paste name + value → **Add secret**

---

## EC2 Instance Setup

### Minimum Requirements
- **OS**: Ubuntu 22.04 LTS or 24.04 LTS
- **Instance type**: `t2.micro` (free tier) or larger
- **Storage**: 20 GB+ (Parquet data accumulates)
- **Security Group inbound rules**:

| Port | Protocol | Source | Purpose |
|---|---|---|---|
| 22 | TCP | Your IP (or GitHub Actions IPs) | SSH / deployment |
| 8000 | TCP | 0.0.0.0/0 | FastAPI ingestion API |
| 8501 | TCP | 0.0.0.0/0 | Streamlit dashboard |
| 9001 | TCP | Your IP only | MinIO web console (optional) |

### One-time server setup
```bash
# SSH into the instance
ssh -i ~/.ssh/your-key.pem ubuntu@<EC2_HOST>

# Install Docker
sudo apt-get update
sudo apt-get install -y docker.io docker-compose-plugin
sudo systemctl enable --now docker
sudo usermod -aG docker ubuntu   # avoid needing sudo for docker commands

# Log out and back in for the group change to take effect
exit
ssh -i ~/.ssh/your-key.pem ubuntu@<EC2_HOST>

# Create the deployment directory
sudo mkdir -p /opt/iceberg_lakehouse
sudo chown ubuntu:ubuntu /opt/iceberg_lakehouse

# Create .env from the template (fill in real values)
cp .env.example /opt/iceberg_lakehouse/.env
nano /opt/iceberg_lakehouse/.env
```

---

## How the CI/CD Pipeline Works

```
Push to main
    │
    ▼
┌─────────────────────────────────────┐
│  Job 1: test (ubuntu-latest runner) │
│  ├─ Spin up MinIO service container │
│  ├─ pip install requirements/api.txt│
│  ├─ ruff check (lint)               │
│  └─ pytest tests/ --junitxml=...    │
└──────────────┬──────────────────────┘
               │ (only on push to main, tests passed)
               ▼
┌─────────────────────────────────────┐
│  Job 2: deploy                      │
│  ├─ Configure SSH key               │
│  ├─ rsync ./ → EC2:/opt/iceberg_... │
│  │    (excludes .git, .env, cache)  │
│  ├─ SSH: docker compose up --build  │
│  └─ Health check GET /health        │
└─────────────────────────────────────┘
```

### What gets rsynced
The deploy step uses `--exclude '.git' --exclude '.env' --exclude '__pycache__'`
so your `.env` secrets are **never transferred** — they must exist on the server
already (created during one-time setup above).

---

## Manual Deployment (without CI/CD)

```bash
# From your local machine
rsync -avz --exclude '.git' --exclude '.env' --exclude '__pycache__' \
  ./ ubuntu@<EC2_HOST>:/opt/iceberg_lakehouse/

ssh ubuntu@<EC2_HOST> "
  cd /opt/iceberg_lakehouse &&
  docker compose pull &&
  docker compose up --build -d &&
  docker compose ps
"
```

---

## Checking Deployment Health

```bash
# API health
curl http://<EC2_HOST>:8000/health

# List tables
curl http://<EC2_HOST>:8000/tables

# View logs
ssh ubuntu@<EC2_HOST> "cd /opt/iceberg_lakehouse && docker compose logs -f"
```

---

## Rollback

```bash
ssh ubuntu@<EC2_HOST> "
  cd /opt/iceberg_lakehouse &&
  docker compose down &&
  git checkout HEAD~1 &&
  docker compose up --build -d
"
```

---

## Environment Variables on EC2

After `make up` runs on EC2, all config comes from `/opt/iceberg_lakehouse/.env`.
Key values to set for production:

```bash
# Change default MinIO credentials
MINIO_ACCESS_KEY=<strong-random-key>
MINIO_SECRET_KEY=<strong-random-secret>

# Change default Postgres credentials
POSTGRES_USER=<user>
POSTGRES_PASSWORD=<strong-password>

# Set your desired weather monitoring location
OPEN_METEO_LATITUDE=28.61   # example: New Delhi
OPEN_METEO_LONGITUDE=77.20
```
