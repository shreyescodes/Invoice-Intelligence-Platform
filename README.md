# Invoice Intelligence Platform (IIP)

[![Build and Deploy](https://github.com/shreyescodes/Invoice-Intelligence-Platform/actions/workflows/deploy.yml/badge.svg)](https://github.com/shreyescodes/Invoice-Intelligence-Platform/actions/workflows/deploy.yml)
[![Python Package](https://github.com/shreyescodes/Invoice-Intelligence-Platform/actions/workflows/ci.yml/badge.svg)](https://github.com/shreyescodes/Invoice-Intelligence-Platform/actions/workflows/ci.yml)

The **Invoice Intelligence Platform (IIP)** is an enterprise-grade, AI-powered accounts-payable automation system. It streamlines the invoice processing lifecycle by automating data extraction, validation, anomaly detection, and ERP synchronization.

## 📖 Documentation

Detailed documentation is available in the `docs/` directory:

- [Architecture & Design](docs/architecture.md) - System design, tech stack, and component interactions.
- [Local Setup & Deployment](docs/setup.md) - Instructions for running the stack locally and deploying to Azure.
- [API Reference](docs/api.md) - Documentation of the FastAPI endpoints and models.
- [Contributing Guidelines](CONTRIBUTING.md) - Standards for contributing to the repository.

## 🚀 Overview

The platform ingests vendor invoices, extracts structured data utilizing OCR and Large Language Models, and validates the extracted entities against SAP purchase orders. A machine-learning anomaly detection model evaluates the transaction to determine if human intervention is required. Approved invoices are automatically synchronized back to SAP, while analytical data is pushed to a Snowflake data warehouse for business intelligence.

### Core Capabilities

- **Intelligent Extraction:** Combines Azure Document Intelligence with LLMs to precisely extract line items, taxes, and vendor details from unstructured PDFs.
- **Automated Validation:** Integrates with ERP systems (SAP) to validate PO numbers, vendor existence, and financial limits.
- **Anomaly Detection:** Utilizes an Isolation Forest ML model to score invoices for anomalous patterns, mitigating fraud and processing errors.
- **Orchestration:** Employs Azure Durable Functions for stateful, resilient workflow execution, including manual human-in-the-loop approval wait states.
- **Natural Language Analytics:** Features an NL-to-SQL interface powered by LLMs to query the Snowflake data warehouse using natural language.

## 🛠️ Technology Stack

- **Frontend:** React, Vite, TypeScript, Tailwind CSS
- **Backend:** Python 3.12, FastAPI, Pydantic v2
- **Cloud (Azure):** Durable Functions, Cosmos DB, Blob Storage, Key Vault, Document Intelligence, Azure OpenAI, Managed Identity
- **Data & ML:** Snowflake, scikit-learn, joblib
- **DevOps:** GitHub Actions, OpenTelemetry, Prometheus, Grafana

## 🛡️ License
This project is licensed under the MIT License - see the LICENSE file for details.
