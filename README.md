# Aequitas: Real-Time Algorithmic Fairness Audit Platform

Aequitas is an event-driven auditing platform designed to monitor, detect, and explain algorithmic bias in high-throughput decision-making systems.

The system utilizes a microservices architecture to process simulated loan application streams in real-time. It leverages **Kafka** for event streaming, **Redis** for high-speed metric aggregation, and a **Generative AI (Flan-T5)** pipeline to provide human readable explanations for automated rejection decisions.

## Core Features

* **Real-Time Bias Detection:** Calculates the **Disparate Impact Ratio (DIR)** on live data streams to detect immediate deviations in fairness across protected demographic groups (e.g., Sex, Race).
* **Event-Driven Architecture:** Decouples decision logic from auditing logic using Apache Kafka to ensure zero-latency impact on the main application.
* **Generative AI Explainability:** Prompt engineering on **Google Flan-T5** generates natural language justifications for loan denials, translating complex feature vectors into user-friendly audits.
* **Secure Dashboard:** A React-based executive dashboard secured via **OIDC (Keycloak)**, providing live visualization of approval rates, bias alerts, and historical logs.
* **Immutable Audit Trail:** All decisions and their corresponding AI-generated explanations are persisted in **Supabase (PostgreSQL)** for compliance and retrospective analysis.

## System Architecture

The project is containerized using Docker and orchestrated via Docker Compose.

| Component | Technology | Description |
| --- | --- | --- |
| **Frontend** | React, TypeScript, Tailwind | Real-time dashboard with OIDC authentication and live metric polling. |
| **Backend API** | Python, FastAPI | Serves ML predictions, manages GenAI inference, and handles database writes. |
| **ML Engine** | Scikit-Learn, Hugging Face | Hosts the decision model (RandomForest) and the explanation model (Flan-T5). |
| **Message Broker** | Apache Kafka | Handles asynchronous event streaming between the decision engine and the bias detector. |
| **Real-Time Store** | Redis | Stores ephemeral metrics for the live dashboard. |
| **Persistent Store** | Supabase (PostgreSQL) | Long-term storage for audit logs and decision history. |
| **Identity Provider** | Keycloak | Manages Role-Based Access Control (RBAC) and Single Sign-On (SSO). |

## Logic & Methodology

### 1. Bias Detection (The Watchdog)

The system implements a rolling-window consumer that monitors the `raw_decisions` topic. It calculates the **Disparate Impact Ratio (DIR)**.

### 2. GenAI Explanation Pipeline

To bridge the gap between black-box ML and human understanding, the system uses a hybrid approach:

1. **Rule Extraction:** Python logic identifies key negative factors (e.g., "High Capital Loss").
2. **Style Transfer:** The **Flan-T5-Small** model rewrites these factors into a polite, professional notification letter.

## Installation & Setup

### Prerequisites

* Docker & Docker Compose
* Python 3.10+
* Node.js 18+

### 1. Clone the Repository

```bash
git clone https://github.com/risheeee/Aequitas.git
cd Aequitas

```

### 2. Environment Configuration

Create a `.env` file in the root directory:

```ini

SUPABASE_URL = your_supabase_url
SUPABASE_KEY = your_supabase_anon_key
KAFKA_BOOTSTRAP_SERVERS = localhost:9093

```

### 3. Build and Run Infrastructure

Start the containerized services (Keycloak, Kafka, Zookeeper):

```bash
docker-compose up -d

```

### 4. Start Microservices

**Terminal 1: Backend API**

```bash
uvicorn backend.main:app --reload

```

**Terminal 2: Bias Detector (Worker)**

```bash
python backend/bias_detector.py

```

**Terminal 3: Traffic Generator (Producer)**

```bash
python backend/producer.py

```

**Terminal 4: Frontend**

```bash
cd frontend
npm install
npm run dev

```

## Usage

1. Access the **Dashboard** at `http://localhost:5173`.
2. Log in via **Keycloak SSO** (Default: `admin` / `admin`).
3. Observe the traffic generator simulating applicants.
4. Monitor the **Live Audit Status** card. If the simulated model exhibits bias, the status will shift to **RED**.
5. Click **"View Report"** on any decision log to view the GenAI-generated explanation.