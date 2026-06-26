<div align="center">

<img src="static/favicon.png" alt="Queuei" width="80" style="border-radius: 16px;" />

# Queuei

### YouTube Intelligence Terminal

**Monitor playlists · Summarise with Gemini · Search semantically · Visualise entities**

[![Python](https://img.shields.io/badge/Python-3.14-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![Django](https://img.shields.io/badge/Django-6.0.2-092E20?style=flat-square&logo=django&logoColor=white)](https://djangoproject.com/)
[![MongoDB](https://img.shields.io/badge/MongoDB-Atlas-47A248?style=flat-square&logo=mongodb&logoColor=white)](https://www.mongodb.com/atlas)
[![Gemini](https://img.shields.io/badge/Google-Gemini-4285F4?style=flat-square&logo=google&logoColor=white)](https://ai.google.dev/)
[![Docker](https://img.shields.io/badge/Docker-ready-2496ED?style=flat-square&logo=docker&logoColor=white)](https://www.docker.com/)
[![License](https://img.shields.io/badge/License-MIT-green?style=flat-square)](LICENSE)

<br/>

> A self-hosted platform that watches your YouTube playlists, processes every video through a configurable Gemini prompt, and surfaces the intelligence through a dark-mode SPA — complete with RAG chat, entity relationship graphs, full-text search, and live analytics.

</div>

---

## ✨ Features at a glance

| | Feature | Description |
|---|---|---|
| 📚 | **Stacks** | Playlists as visual cards with YouTube thumbnails and record counts |
| 📰 | **Article Reader** | Markdown-rendered reports with entity tags and related content |
| 🤖 | **Intel Chat** | Conversational RAG — vector search + Gemini synthesis with memory |
| 🕸️ | **Nexus Graph** | Force-directed graph linking reports to people, locations, organisations |
| 📊 | **Insights** | Entity frequency, volume trends, category breakdown, archive health |
| ⚡ | **Full-text Search** | MongoDB text index with weighted scoring + regex fallback |
| 🔖 | **Bookmarks** | Per-user saved reports persisted in PostgreSQL |
| ⏱️ | **Cron Manager** | Schedule pipeline runs with 5-part cron expressions |
| 🎛️ | **Command Center** | CRUD for prompt templates and task types — no code changes needed |
| 📈 | **API Usage** | Live Gemini request + token tracking vs. free-tier daily limits |

---

## 🏗️ Architecture

Queuei is split into two Django apps backed by two databases.

```mermaid
graph TB
    subgraph Django["⚡ Django Project"]
        direction LR
        R["📂 records/\nFrontend · API · Auth"]
        T["📂 tasks/\nIngestion Pipeline"]
    end

    R -->|Django ORM| PG
    T -->|Django ORM| PG
    R -->|pymongo| MG
    T -->|pymongo| MG

    PG[("🐘 PostgreSQL\n\nUsers · Auth\nBookmarks\nTaskConfig\nGlobalSetting\nCronJob\nTranscriptCache\nApiUsageLog")]

    MG[("🍃 MongoDB Atlas\n\nmass_records\nvalue · entities\nembedding · playlist_id\n\nvector_index\ncosine · 3072-dim")]
```

### Pipeline data flow

```mermaid
flowchart TD
    A([🎬 YouTube Playlist]) --> B[yt-dlp\nFetch metadata & video IDs]
    B --> C{Transcript\navailable?}

    C -- "Method 1" --> D[youtube-transcript-api]
    C -- "Method 2 fallback" --> E[RapidAPI]
    C -- "Method 3 fallback" --> F[Supadata]

    D & E & F --> G[(PostgreSQL\nTranscriptCache)]
    G --> H[Gemini LLM\nConfigurable prompt template]
    H --> I[Gemini Embeddings\ngemini-embedding-001 · 3072-dim]
    I --> J[(MongoDB Atlas\nmass_records)]

    J --> K[Dashboard SPA]
    K --> L[📚 Stacks]
    K --> M[🤖 Intel Chat RAG]
    K --> N[🕸️ Nexus Graph]
    K --> O[📊 Insights]
```

### Request flow (Intel Chat)

```mermaid
sequenceDiagram
    participant U as User
    participant D as Dashboard
    participant V as views.py
    participant G as Gemini API
    participant M as MongoDB

    U->>D: Types query + sends history
    D->>V: POST /intel-chat/ {query, history}
    V->>G: embed_content(query)
    G-->>V: 3072-dim query vector
    V->>M: $vectorSearch (limit 6)
    M-->>V: Top matching documents
    V->>G: generate_content(prompt + context + history)
    G-->>V: Synthesised answer
    V-->>D: {answer, sources[id, title, date, playlist]}
    D-->>U: Rendered response + clickable source chips
```

---

## 🗂️ Project structure

```
base/
├── core/                        Django project
│   ├── settings.py
│   └── urls.py
│
├── records/                     Frontend app
│   ├── models.py                Bookmark · ApiUsageLog
│   ├── views.py                 All dashboard + API endpoints
│   ├── urls.py
│   ├── migrations/
│   └── templates/
│       ├── dashboard.html       ◀ Main SPA (Alpine.js v3)
│       ├── login.html
│       ├── signup.html
│       ├── settings.html
│       └── cron_manager.html
│
├── tasks/                       Pipeline app
│   ├── models.py                TaskConfiguration · GlobalSetting · CronJob · TranscriptCache
│   ├── views.py                 Pipeline trigger endpoint
│   ├── config.py                MongoDB client · pipeline config loader
│   ├── scheduler.py             APScheduler integration
│   └── script_custom/
│       ├── youtube_llm_pipeline.py   ◀ Core pipeline class
│       ├── backfill_entity.py        Entity extraction for existing docs
│       └── slack_alerting.py
│
├── static/                      favicon.png
├── Dockerfile
├── entrypoint.sh                migrate → gunicorn
├── build.sh                     Local Docker build + run
└── requirements.txt
```

---

## 🚀 Getting started

### Prerequisites

| Requirement | Notes |
|---|---|
| 🐍 Python 3.14 | |
| 🐘 PostgreSQL | [Neon](https://neon.tech) free tier works great |
| 🍃 MongoDB Atlas | Free M0 cluster; needs a vector search index (see below) |
| 🤖 Google AI Studio key | [Get one here](https://aistudio.google.com/apikey) |
| 🐳 Docker | For containerised deployment only |
| ⚡ RapidAPI key | Optional — transcript fallback |
| 📡 Supadata key | Optional — transcript fallback |
| 💬 Slack webhook | Optional — pipeline alerts |

### 1 · Clone & install

```bash
git clone <your-repo-url>
cd base
pip install -r requirements.txt
```

### 2 · Configure environment

Create `.env` in the project root:

```env
# ── Django ────────────────────────────────────────────
DJANGO_SECRET_KEY=your-secret-key-here
ALLOWED_HOSTS=localhost,127.0.0.1,your-domain.com
DEBUG=False

# ── PostgreSQL ────────────────────────────────────────
DATABASE_URL=postgres://user:password@host/dbname

# ── MongoDB Atlas ─────────────────────────────────────
DB_USER=your-mongo-user
DB_PASSWORD=your-mongo-password
DB_URL=cluster0.xxxxx.mongodb.net
MONGO_DB_NAME=queuei

# ── Google Gemini ─────────────────────────────────────
GOOGLE_API_KEY=AIza...
GEN_AI_API_KEY=AIza...

# ── Pipeline defaults (editable later via /settings/) ─
YOUTUBE_PLAYLIST_IDS=PLxxxxxx,PLyyyyyy
PLAYLIST_FETCH_LIMIT=10
AI_MODEL=gemini-2.0-flash
EXECUTOR_WORKERS=1
INBETWEEN_TASK_SLEEP=15
EXTRA_DOCUMENT_ARGS={}

# ── Optional ──────────────────────────────────────────
RAPID_API_KEY=
RAPID_API_HOST=
RAPID_API_URL=
SUPADATA_API_KEY=
SLACK_WEBHOOK_URL=
```

### 3 · Initialise the database

```bash
python manage.py migrate
python manage.py createsuperuser
```

### 4 · Run

```bash
python manage.py runserver
```

Open **http://localhost:8000** — log in with your superuser, then visit `/admin/` to activate users and assign `Analyst` or `Supervisor` group membership.

---

## 🐳 Docker deployment

```bash
./build.sh
```

This script removes any existing container, rebuilds the image (`base_core`), and runs it on port `8000` using the `.env` file. The `entrypoint.sh` runs migrations automatically before starting Gunicorn.

```
Gunicorn: 1 sync worker · 600 s timeout · port 8000
```

To deploy on a cloud VM or PaaS, push the image and inject the `.env` variables as container environment variables.

---

## 🔍 MongoDB vector index

Intel Chat and Related Reports require a vector search index. Create it from the **Atlas UI → Search → Create Index → JSON editor**:

```json
{
  "name": "vector_index",
  "type": "vectorSearch",
  "definition": {
    "fields": [
      {
        "type": "vector",
        "path": "embedding",
        "numDimensions": 3072,
        "similarity": "cosine"
      }
    ]
  }
}
```

---

## ⚙️ Runtime configuration

All pipeline settings live in the `GlobalSetting` PostgreSQL table and are editable at `/settings/` (superuser only). **Changes take effect immediately** — no restart required.

| Key | Description | Default |
|---|---|---|
| `YOUTUBE_PLAYLIST_IDS` | Comma-separated YouTube playlist IDs | from `.env` |
| `PLAYLIST_FETCH_LIMIT` | Recent videos to fetch per playlist per run | `10` |
| `AI_MODEL` | Gemini model name | `gemini-2.0-flash` |
| `EXECUTOR_WORKERS` | Thread pool size for concurrent processing | `1` |
| `INBETWEEN_TASK_SLEEP` | Seconds to pause between thread batches | `15` |
| `EXTRA_DOCUMENT_ARGS` | JSON fields merged into every MongoDB document | `{}` |

---

## 🔁 Triggering the pipeline

```bash
# Run the summarise task
curl -X POST http://localhost:8000/tasks/queuei/summarize/

# Run any other configured task
curl -X POST http://localhost:8000/tasks/queuei/<task_key>/
```

### Pipeline execution steps

```mermaid
flowchart LR
    A[POST /tasks/queuei/task_key] --> B[Fetch playlist videos\nvia yt-dlp]
    B --> C[Check TranscriptCache\nPostgreSQL]
    C -- Cache miss --> D[Fetch transcript\n3-source fallback]
    D --> E[Cache transcript]
    C -- Cache hit --> F
    E --> F[Gemini LLM\nprompt_template + transcript]
    F --> G[Gemini Embeddings\n3072-dim vector]
    G --> H[Insert document\nMongoDB]
```

### Adding a new task type

```
1. Dashboard → Command Center → New Task
2. Set task_key, prompt template (include {transcript}), target collection
3. POST to /tasks/queuei/<your_task_key>/
```

---

## 🌐 API reference

### `records` app

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| `GET` | `/` | Login | Dashboard SPA |
| `GET` | `/records/` | Login | Paginated records `?offset=N&playlist_id=X` |
| `GET` | `/search/` | Login | Full-text search `?q=query` |
| `GET` | `/get-report/<id>/` | Login | Full report with entities |
| `GET` | `/related/<id>/` | Login | Semantically similar reports |
| `GET` | `/bookmarks/` | Login | Current user's bookmarked IDs |
| `POST` | `/bookmark/` | Login | Toggle bookmark `{report_id, title}` |
| `POST` | `/intel-chat/` | Login | RAG chat `{query, history[]}` |
| `GET` | `/nexus-data/` | Login | Force-graph nodes + links JSON |
| `GET` | `/entity-stats/` | Login | Entity counts + archive metrics (10 min cache) |
| `GET` | `/usage-stats/` | Login | Gemini API usage by day |
| `POST` | `/command-center/` | Supervisor | Task CRUD |
| `POST` | `/settings/` | Superuser | GlobalSetting upsert |
| `GET/POST` | `/cron/` | Superuser | Cron job management |

### `tasks` app

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/tasks/queuei/<task_key>/` | Trigger ingestion pipeline |
| `POST` | `/tasks/alert/` | Send Slack alert |
| `POST` | `/tasks/backfill_entities/` | Extract entities for existing docs |

---

## 🔐 Access control

```mermaid
flowchart TD
    A([User visits /]) --> B{Logged in?}
    B -- No --> C[/login/]
    B -- Yes --> D{Group membership?}
    D -- Analyst or Supervisor --> E[Dashboard — full access]
    D -- Neither --> F[access_denied.html]
    E --> G{Supervisor or Superuser?}
    G -- Yes --> H[Command Center · Settings · Cron]
    G -- No --> I[Read-only features only]
```

> New accounts are created with `is_active=False`. A superuser must activate them and assign a group via `/admin/`.

---

## 🧠 Design decisions

<details>
<summary><strong>🗄️ Why two databases?</strong></summary>

PostgreSQL handles relational, transactional data — users, config, bookmarks. MongoDB handles high-volume schema-flexible content and provides the `$vectorSearch` aggregation stage for semantic search, which is not available in vanilla PostgreSQL without extensions.

</details>

<details>
<summary><strong>Why raw pymongo instead of an ODM?</strong></summary>

`pymongo` gives direct access to MongoDB's aggregation pipeline — essential for `$vectorSearch`, `$group`, `$project`, and weighted `$text` indexes. An ODM abstraction would constrain or hide these capabilities.

</details>

<details>
<summary><strong>Why in-memory caching for entity stats?</strong></summary>

The entity aggregation scans every document in the collection. At scale this is expensive. A 10-minute module-level cache (`_ENTITY_STATS_CACHE`) avoids re-scanning on every Insights tab visit while keeping data reasonably fresh.

</details>

<details>
<summary><strong>Why transcript caching in PostgreSQL?</strong></summary>

Transcript APIs have rate limits and occasional failures. Caching in `TranscriptCache` means a Gemini failure does not require re-fetching the transcript — the pipeline can retry the LLM step on the next run without another external API call.

</details>

<details>
<summary><strong>Why APScheduler over Celery?</strong></summary>

Queuei runs as a single Gunicorn worker with a long timeout, making an in-process scheduler a natural fit. Celery would require a separate broker (Redis/RabbitMQ) and worker process, adding infrastructure overhead that isn't justified for the current workload.

</details>

---

## 📦 Tech stack

| Layer | Technology | Version |
|---|---|---|
| Language | ![Python](https://img.shields.io/badge/Python-3776AB?style=flat-square&logo=python&logoColor=white) | 3.14 |
| Web framework | ![Django](https://img.shields.io/badge/Django-092E20?style=flat-square&logo=django&logoColor=white) | 6.0.2 |
| Relational DB | ![PostgreSQL](https://img.shields.io/badge/PostgreSQL-4169E1?style=flat-square&logo=postgresql&logoColor=white) Neon | — |
| Document DB | ![MongoDB](https://img.shields.io/badge/MongoDB_Atlas-47A248?style=flat-square&logo=mongodb&logoColor=white) | — |
| LLM + Embeddings | ![Google Gemini](https://img.shields.io/badge/Google_Gemini-4285F4?style=flat-square&logo=google&logoColor=white) `google-genai` | 1.64.0 |
| Transcript — primary | ![YouTube](https://img.shields.io/badge/youtube--transcript--api-FF0000?style=flat-square&logo=youtube&logoColor=white) | 1.2.4 |
| Transcript — fallback 1 | ![RapidAPI](https://img.shields.io/badge/RapidAPI-0055DA?style=flat-square&logo=rapidapi&logoColor=white) | — |
| Transcript — fallback 2 | ![Supadata](https://img.shields.io/badge/Supadata-6366F1?style=flat-square&logoColor=white) | 1.6.0 |
| Video metadata | ![yt-dlp](https://img.shields.io/badge/yt--dlp-FF0000?style=flat-square&logo=youtube&logoColor=white) | 2026.2.21 |
| Scheduling | ![APScheduler](https://img.shields.io/badge/APScheduler-3ECF8E?style=flat-square&logoColor=white) | 3.11.0 |
| Frontend reactivity | ![Alpine.js](https://img.shields.io/badge/Alpine.js-8BC0D0?style=flat-square&logo=alpinedotjs&logoColor=black) | v3 (CDN) |
| CSS | ![Tailwind CSS](https://img.shields.io/badge/Tailwind_CSS-06B6D4?style=flat-square&logo=tailwindcss&logoColor=white) | v3 (CDN) |
| Icons | ![Font Awesome](https://img.shields.io/badge/Font_Awesome-528DD7?style=flat-square&logo=fontawesome&logoColor=white) | 6.0.0 |
| Force graph | ![D3.js](https://img.shields.io/badge/force--graph_+_D3.js-F9A03C?style=flat-square&logo=d3dotjs&logoColor=white) | v7 |
| WSGI server | ![Gunicorn](https://img.shields.io/badge/Gunicorn-499848?style=flat-square&logo=gunicorn&logoColor=white) + Whitenoise | — |
| Container | ![Docker](https://img.shields.io/badge/Docker-2496ED?style=flat-square&logo=docker&logoColor=white) | — |

---

<div align="center">
  <sub>Built with Django · MongoDB · Google Gemini</sub>
</div>
