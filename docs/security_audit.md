# Meridian Security & DPDP Act Compliance Audit

## Executive Summary
This document provides the security audit review and compliance verification for Meridian under India's Digital Personal Data Protection (DPDP) Act 2023 and global health data sovereignty frameworks.

## Security Control Verifications

### 1. Data Sovereignty & Network Boundary Controls
- **Finding**: Raw patient records and staff identity tables never leave the edge PHC node SQLite instance.
- **Verification**: Only encrypted model weights ($[m_i, c_i]$) and noised aggregate counts are transmitted across network boundaries.

### 2. Encryption & Tokenization Standards
- **Finding**: Staff identity fields (`staff_id`) are encrypted using `cryptography` Fernet symmetric keys (AES-128 in CBC mode with PKCS7 padding and HMAC-SHA256).
- **Verification**: Display fields render SHA-256 tokens (`TOK-XXXX`) preventing reverse identity resolution.

### 3. Differential Privacy Guarantee
- **Finding**: Aggregate counts shown above PHC level employ $(\epsilon, \delta)$-Differential Privacy noise injection ($\epsilon = 1.0, \delta = 10^{-5}$).
- **Verification**: Privacy budget consumption is audited per query, terminating queries if cumulative budget threshold is reached.

### 4. Role-Based Access Control (RBAC)
- **Finding**: Access controls strictly segregate `PHC_STAFF`, `DISTRICT_OFFICER`, and `NATIONAL_ADMIN` privileges.
