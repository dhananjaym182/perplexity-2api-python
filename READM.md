# 🚀 Perplexity-2API Python (Universal Edition)

<div align="center">

![Python](https://img.shields.io/badge/Python-3.8%2B-blue?style=for-the-badge&logo=python)
![FastAPI](https://img.shields.io/badge/FastAPI-High%20Performance-green?style=for-the-badge&logo=fastapi)
![License](https://img.shields.io/badge/License-Apache%202.0-orange?style=for-the-badge)
![Status](https://img.shields.io/badge/Status-Active%20Development-red?style=for-the-badge)

**Make Perplexity's powerful search capabilities as easy to plug into your AI apps as breathing.**

**Transalate to English and Updated to work on WSL**

[English](./README.md) | [中文文档](./README_中文文档.md)

</div>

---

## 📖 Preface: About Open Source, Freedom and Exploration

Hello! 👋 Welcome to **Perplexity-2API Python**.

In this explosive era of AI, we believe **access to knowledge should be free and convenient**. Perplexity is an amazing tool that combines the reasoning power of LLMs with the breadth of a search engine. The original purpose of this project is to break the barrier of the web UI and convert its capabilities into a standard API interface, so that your favorite tools (such as NextChat, LangChain, etc.) can also gain "online search" superpowers.

This is not just a piece of code, but also an interesting exploration of **reverse engineering, browser automation and human-like interaction**. Whether you are a beginner or an experienced developer, hopefully you can feel the fun of "if others can do it, so can I" here! ✨

---

## 🌟 Project Highlights (Why This?)

What problems does this project solve? What makes it special?

* **⚡ OpenAI-compatible format**: Fully follows the OpenAI API standard (`/v1/chat/completions`), seamlessly compatible with 99% of AI clients.
* **🧠 Intelligent browser management**: Based on **Botasaurus** (an enhanced Selenium wrapper) and **Playwright**, automatically handles complex browser fingerprinting and environment simulation.
* **🛡️ Human-like Turnstile solver**: Built-in Bézier-curve mouse movement algorithm to simulate human "hand shake" and reaction time, gracefully passing Cloudflare verification.
* **🍪 All-in-one Cookie management**:
  * **Visual wizard**: Provides a `config_wizard.py` GUI, supports extracting Cookies from HAR, cURL, PowerShell or even plain text.
  * **Web UI console**: Beautiful built-in web console to manage multiple accounts, view logs and test APIs.
* **🌊 Streaming responses**: Supports SSE (Server-Sent Events) for smooth typewriter-style streaming.
* **🔧 One-click lazy bundle**: `.bat` scripts for Windows, one double-click to run, dependencies auto-installed.

---

## 📂 Project Structure

To help AI crawlers and developers, here is the project layout:

```text
📂 perplexity-2api-python/
├── 📄 main.py                  # [Core] FastAPI main app, API entrypoint
├── 📄 config_wizard.py         # [Tool] Tkinter GUI config wizard
├── 📄 requirements.txt         # [Deps] Python dependencies
├── 📄 install.bat              # [Script] Windows one-click install
├── 📄 start.bat                # [Script] Windows one-click start
├── 📄 start_and_test.ps1       # [Script] PowerShell start & self-test
├── 📂 app/                     # [Source] Core logic
│   ├── 📂 core/                # Config center
│   │   └── 📄 config.py        # Env vars & global config loader
│   ├── 📂 providers/           # Provider logic
│   │   ├── 📄 base_provider.py # Abstract base class
│   │   └── 📄 perplexity_provider.py # [Core] Perplexity implementation (streaming)
│   ├── 📂 services/            # Services
│   │   ├── 📄 browser_service.py # [Core] Botasaurus browser manager & Cookie injection
│   │   └── 📄 turnstile_solver.py # [Black magic] Playwright human-like CAPTCHA solver
│   └── 📂 utils/               # Utilities
│       └── 📄 sse_utils.py     # SSE packet helpers
├── 📂 data/                    # [Data] Local persistence
│   ├── 📂 cookies/             # Cookie JSON per account
│   ├── 📂 sessions/            # Session state & stats per account
│   └── 📂 logs/                # Runtime logs
└── 📂 static/                  # [Frontend] Web UI static assets
    └── 📄 index.html           # Console frontend page
```

---

## 🛠️ Quick Start (Beginner Friendly)

Even if you have never written code, you can still run this project.

### 1. Environment
Make sure you have **Python 3.8+** installed. [Download Python](https://www.python.org/downloads/)

### 2. Download the project
Use Git or download ZIP:

```bash
git clone https://github.com/lza6/perplexity-2api-python.git
cd perplexity-2api-python
```

### 3. One-click install & start (Windows)
1. Double-click **`install.bat`** in the project folder.
   * It will automatically install all required libraries.
2. Double-click **`start.bat`**.
   * The service will start and automatically open the Web console.

### 4. Configure account (most important step)
After the service starts, your browser will open `http://127.0.0.1:8092`.

1. In the console, click **"Quick Login Account"**.
2. A browser window will pop up; log into your Perplexity account there.
3. After login, the program will automatically capture and save the Cookies.
4. Done. You can now use the API.

---

## 💻 Technical Deep Dive (Hardcore Mode)

For developers and AI agents, this is the soul of the project.

### 1. Architecture
The project uses a **layered architecture**, decoupling API, business logic and browser operations.

* **Interface Layer (`main.py`)**: High-performance HTTP API using FastAPI.
* **Provider Layer (`perplexity_provider.py`)**: Converts OpenAI-style requests into Perplexity's internal JSON format and parses SSE streaming responses.
* **Service Layer (`browser_service.py`)**: The core of the core. Uses **Botasaurus** (on top of Selenium) to maintain a persistent browser instance. It:
  * Injects and keeps Cookies alive.
  * Detects Cloudflare shields.
  * Automatically refreshes when 403 is encountered.
* **Solver Layer (`turnstile_solver.py`)**: Uses **Playwright** when strong CAPTCHAs appear.
  * **Algorithm highlight**: Implements `_human_mouse_move` using **Bézier curves** plus random jitter and variable speed to simulate real human mouse movement and bypass behavior detection.

### 2. Tech Stack Rating

| Tech | Difficulty | Innovation | Source | Role |
| :--- | :---: | :---: | :--- | :--- |
| **FastAPI** | ⭐ | ⭐⭐ | Official docs | High-speed async API service |
| **Botasaurus** | ⭐⭐ | ⭐⭐⭐⭐ | GitHub | Powerful anti-fingerprint browser framework, more stable than raw Selenium |
| **SSE Streaming** | ⭐⭐⭐ | ⭐⭐⭐ | HTTP standard | Typewriter effect, better UX |
| **Playwright Stealth** | ⭐⭐⭐ | ⭐⭐⭐⭐ | Community tricks | Hides `navigator.webdriver` etc. to avoid bot detection |
| **Bezier Mouse Algo** | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | Computer graphics | **Core black magic** to make mouse movement human-like and pass Turnstile |

### 3. Key Variables & Logic

* `PPLX_COOKIE`: Core credential. Contains `pplx.visitor-id` and `__Secure-next-auth.session-token`.
* `interactive_login`: Interactive login mode. Instead of cracking complex login encryption, it lets the user log in in a controlled browser and then "steals" the Cookies — a **dimensionality reduction attack**.

---

## 📊 Pros, Cons & Roadmap

### ✅ Pros

1. **Free and powerful**: Use Perplexity's free quota or Pro account to get high-quality web search results.
2. **Local privacy**: All Cookies and data are stored locally under `data/`, never sent to third-party servers.
3. **High availability**: Compared to pure reverse-engineered APIs, browser simulation is more resilient to blocking.
4. **Friendly UI**: Full-featured Web UI, no need to fight with a black terminal.

### ❌ Cons & Gaps

1. **Resource usage**: Needs a browser instance (Chrome), so memory usage is higher than pure HTTP.
2. **CAPTCHA challenges**: Cloudflare keeps upgrading; sometimes manual intervention is still needed (Web UI provides manual verification entry).
3. **Not fully headless**: For some strong detection, a visible browser window is required.

### 🚧 Roadmap

* [ ] **Dockerization**: Provide a standard Dockerfile for NAS/server deployment (needs GPU/headless rendering tweaks).
* [ ] **Multi-account load balancing**: Support multiple accounts and automatic rotation for higher concurrency.
* [ ] **Deeper API reverse engineering**: Try to crack gRPC or lower-level protocols to reduce browser dependency.
* [ ] **MCP support**: Implement Model Context Protocol so more AI agents can call it directly.

---

## 🤖 Blueprint for AI Agents

If you are an AI and want to understand/replicate this project, focus on:

1. **Entry**: Start from `main.py`, understand FastAPI lifecycle (`lifespan`) and dependency injection.
2. **Core**: Dive into `app/services/browser_service.py`. Pay attention to how `_refresh_cookies_with_browser` works with the `@browser` decorator from Botasaurus.
3. **Hard part**: Analyze `_human_mouse_move` in `app/services/turnstile_solver.py`. This is the key to passing behavior verification.
4. **Data flow**: Trace `stream_generator` in `perplexity_provider.py` to see how it parses Perplexity's nested JSON and converts it into SSE.

---

## 🤝 Contribution & License

This is an open-source project under **Apache 2.0**. You can freely use, modify and distribute it, including for commercial use (within legal bounds).

You are encouraged to:

* 🐛 Open issues for bugs.
* 💡 Submit pull requests.
* ⭐ Star the repo — it really helps.

**Disclaimer**: This project is for research and learning only. Do not use it for illegal purposes. Please follow Perplexity's Terms of Service.

---

<div align="center">

**Made with ❤️ by lza6**

*Technology should make humans more free, not more constrained.*

</div>
