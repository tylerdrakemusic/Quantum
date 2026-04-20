# Open Quantum Safe — liboqs Library Assessment

**Research Date:** 2026-04-18  
**Scope:** ⟨ψ⟩Quantum project — quantum cryptography research  
**Source:** https://openquantumsafe.org, https://github.com/open-quantum-safe/liboqs-python  
**liboqs version at time of research:** 0.15.0 (Nov 14, 2025)  
**liboqs-python version at time of research:** 0.12.0 (Jan 16, 2025)

---

## 1. Project Overview

The **Open Quantum Safe (OQS)** project is a Linux Foundation initiative (joined Jan 2024) and a founding member of the **Post-Quantum Cryptography Alliance (PQCA)**. It is co-led by Douglas Stebila and Michele Mosca at the University of Waterloo, with financial backing from Amazon Web Services, the Canadian Centre for Cyber Security, and Microsoft Research.

OQS has two main deliverables:

1. **liboqs** — an open-source C library implementing post-quantum cryptographic algorithms
2. **Protocol integrations** — PQC-enabled versions of OpenSSL (via oqs-provider), OpenSSH, and BoringSSL

**liboqs-python** provides Python 3 bindings for liboqs via ctypes.

---

## 2. Algorithm Inventory and NIST Standardization Status

### Key Encapsulation Mechanisms (KEM)

| Algorithm | Basis | NIST Status |
|---|---|---|
| **ML-KEM-512 / 768 / 1024** | CRYSTALS-Kyber | **FIPS 203 — Finalized standard (Aug 2024)** |
| **HQC-128 / 192 / 256** | Code-based | Under evaluation (NIST PQC Round 4, backup KEM) |
| **FrodoKEM-640/976/1344** | Learning with errors (conservative) | Not selected but included as conservative option |
| **BIKE** | Code-based | Round 4 alternate |
| **Classic McEliece** | Code-based | Round 4 alternate |

**ML-KEM is the primary recommendation** — it is a finalized FIPS standard.

### Digital Signature Algorithms (DSA)

| Algorithm | Basis | NIST Status |
|---|---|---|
| **ML-DSA-44 / 65 / 87** | CRYSTALS-Dilithium | **FIPS 204 — Finalized standard (Aug 2024)** |
| **SLH-DSA (SPHINCS+)** | Hash-based | **FIPS 205 — Finalized standard (Aug 2024)** |
| **FN-DSA (FALCON-512/1024)** | NTRU lattice | **FIPS 206 — Finalized standard (Aug 2024)** |
| **MAYO / cross-rsdp / UOV** | MQ/code-based | NIST additional signatures round |

**All four FIPS-standardized algorithms are implemented.** The finalization of FIPS 203/204/205/206 in August 2024 marks a clear inflection point — these are no longer experimental.

### Stateful Signature Algorithms (for long-lived key pairs)

| Algorithm | Notes |
|---|---|
| **XMSS / XMSSMT** | Hash-based, RFC 8391 standardized. Statefulness requires careful key management. |
| **LMS / HSS** | Hash-based, NIST SP 800-208 standardized. |

These are mature but require tracking state across signatures to avoid reuse — unsuitable for general-purpose use without careful infrastructure.

---

## 3. Python Integration

### Architecture

liboqs-python wraps liboqs via Python's `ctypes` module. The Python layer is thin — it calls into the compiled C shared library (`oqs.dll` on Windows, `liboqs.so` on Linux).

**Three main classes:**

```python
import oqs

# Key Encapsulation
kem = oqs.KeyEncapsulation("ML-KEM-768")
public_key = kem.generate_keypair()
ciphertext, shared_secret_server = kem.encap_secret(public_key)
shared_secret_client = kem.decap_secret(ciphertext)

# Signature
sig = oqs.Signature("ML-DSA-65")
public_key = sig.generate_keypair()
signature = sig.sign(b"message")
is_valid = sig.verify(b"message", signature, public_key)

# Enumerate available algorithms
print(oqs.get_enabled_kem_mechanisms())
print(oqs.get_enabled_sig_mechanisms())
```

**Auto-install behavior:** If `liboqs.dll` is not found at import time, liboqs-python will automatically download, build, and install liboqs from source. This requires CMake and a C compiler (MSVC on Windows).

### Installation on Tyler's Machine (Windows)

**Option A — Manual build (recommended for reproducibility):**
```batch
# Tyler must approve before running
git clone --depth=1 https://github.com/open-quantum-safe/liboqs
cmake -S liboqs -B liboqs/build -DCMAKE_WINDOWS_EXPORT_ALL_SYMBOLS=TRUE -DBUILD_SHARED_LIBS=ON -DCMAKE_INSTALL_PREFIX="C:\liboqs"
cmake --build liboqs/build --parallel 8
cmake --build liboqs/build --target install
set PATH=%PATH%;C:\liboqs\bin

git clone --depth=1 https://github.com/open-quantum-safe/liboqs-python
cd liboqs-python
C:\G\python.exe -m pip install .
```

**Option B — Let liboqs-python auto-build (easier, requires CMake + MSVC):**
```batch
# Tyler must approve before running
C:\G\python.exe -m pip install git+https://github.com/open-quantum-safe/liboqs-python
```

**Prerequisites needed on Tyler's machine:**
- CMake (https://cmake.org/download/)
- Visual Studio Build Tools (C compiler for Windows) or MSVC
- git (likely already present)

---

## 4. Licensing

| Component | License |
|---|---|
| **liboqs** (C library) | **Apache 2.0** |
| **liboqs-python** (Python bindings) | **MIT** |

> **Correction from task brief:** liboqs-python is **MIT licensed**, not Apache 2.0. The underlying C library (liboqs) is Apache 2.0. Both are permissive open-source licenses with no copyleft restrictions — suitable for Tyler's private workspace projects.

---

## 5. Security Audit Status

Trail of Bits released a **public security assessment of liboqs in April 2025** (covering a 2024 audit engagement). This is a significant positive signal — the library has received independent professional security review. The report is publicly available at the OQS GitHub.

The OQS project explicitly states that liboqs is designed for **prototyping and evaluation**, and strongly recommends using NIST-standardized algorithms rather than pre-standard candidates for deployment. They also recommend **hybrid cryptography** (PQC + classical) for maximum assurance during the transition period.

---

## 6. Suitability for Tyler's Workspace

### Assessment

| Criterion | Assessment |
|---|---|
| Implements finalized FIPS standards | ✅ ML-KEM, ML-DSA, SLH-DSA, FN-DSA all present |
| Python support | ✅ liboqs-python maintained and tested on Windows |
| Windows support | ✅ Confirmed, with PATH setup requirements |
| License | ✅ MIT/Apache 2.0 — no restrictions for private use |
| Install complexity | ⚠️ Requires CMake + C compiler build step; not a simple `pip install` |
| Production readiness | ⚠️ "Prototyping and evaluation" per project's own disclaimer |
| Independent security audit | ✅ Trail of Bits audit published April 2025 |
| Active maintenance | ✅ liboqs 0.15.0 released Nov 2025, regular release cadence |

### Verdict

**liboqs is the correct library to evaluate for Tyler's workspace PQC needs.** It implements all four finalized FIPS PQC standards, has Python bindings, Windows support, and an independent security audit. The "prototyping" disclaimer reflects appropriate caution about the broader PQC ecosystem, not a specific flaw — the FIPS-standardized algorithms themselves (ML-KEM, ML-DSA, etc.) are vetted.

The **installation complexity is the primary blocker** for immediate use — Tyler needs CMake and MSVC Build Tools before `pip install` can succeed. This is a one-time setup cost.

### Cross-Project Shared Protection Layer

liboqs is well-suited to serve as the cryptographic backend for a shared utility used across:
- **∞Life** — encrypting SQLite health records, API keys
- **❤Music** — protecting catalog metadata, session keys
- **⟨ψ⟩Quantum** — protecting IBM Quantum API credentials and cache files

The shared utility design is detailed in `quantum-safe-encryption-design.md`.

---

## 7. Open Questions for Tyler

1. **Is CMake + Visual Studio Build Tools already installed?** Run `cmake --version` and `cl` in a command prompt to check. If not, this is the first prerequisite.
2. **Python environment:** Should the shared crypto utility use Tyler's global `C:\G\python.exe` or a venv? A venv is cleaner for liboqs-python's native dependency.
3. **liboqs-python version pin:** 0.12.0 is the latest Python binding as of research date; liboqs itself is at 0.15.0. The Python binding lags slightly behind the C library — verify compatibility matrix before installing.

---

## 8. References

- Open Quantum Safe project: https://openquantumsafe.org
- liboqs GitHub: https://github.com/open-quantum-safe/liboqs
- liboqs-python GitHub: https://github.com/open-quantum-safe/liboqs-python
- Trail of Bits security audit (2025): https://github.com/trailofbits/publications/blob/master/reviews/2025-04-quantum-open-safe-liboqs-securityreview.pdf
- NIST FIPS 203 (ML-KEM): https://doi.org/10.6028/NIST.FIPS.203
- NIST FIPS 204 (ML-DSA): https://doi.org/10.6028/NIST.FIPS.204
- NIST FIPS 205 (SLH-DSA): https://doi.org/10.6028/NIST.FIPS.205
- NIST FIPS 206 (FN-DSA): https://doi.org/10.6028/NIST.FIPS.206
