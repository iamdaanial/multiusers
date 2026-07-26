# MultiUsers Cloud Platform

Self-hosted cloud storage where each company gets its own private space.
Built on ownCloud Infinite Scale (oCIS). This project moves it from Docker to Kubernetes.

## What it does

- Each company (tenant) gets isolated cloud storage
- Runs on ownCloud oCIS
- Being rebuilt on Kubernetes with a full DevOps setup

## Run it locally


Open https://localhost:9200 — login: admin / admin


## Roadmap

- [x] Run oCIS locally
- [x] Admin portal (Python) to create tenants
- [ ] Deploy on Kubernetes (k3s)
- [ ] CI/CD with GitHub Actions
- [ ] GitOps with ArgoCD
- [ ] Monitoring with Prometheus + Grafana


## Tech

Docker · oCIS · Kubernetes · Python · GitHub Actions · ArgoCD · Prometheus · Grafana