# Quantum-Safe Encryption Design for Shared Workspace Protection

**Research Date:** 2026-04-18  
**Scope:** ⟨ψ⟩Quantum → cross-project design (∞Life, ❤Music, ⟨ψ⟩Quantum, ⊕Workspace)  
**Status:** Design proposal — awaiting Tyler approval before implementation  
**Dependencies:** `heisenberg-uncertainty-encryption.md`, `liboqs-assessment.md`

---

## 1. Problem Statement

Tyler's workspace contains sensitive data across three projects:

| Project | Sensitive Data |
|---|---|
| **∞Life** | Health metrics, biomarker logs, supplement/medication protocols, API keys (Oura, Whoop, etc.) |
| **❤Music** | Royalty financial data, distribution credentials, unreleased catalog metadata |
| **⟨ψ⟩Quantum** | IBM Quantum API token, quantum RNG cache (`ty_string_cache.txt`) |

Current protection: **none beyond filesystem access control**. SQLite databases and config files are plaintext. A single compromised machine or accidental sync to cloud storage exposes everything.

The threat model includes:
- Harvest-now-decrypt-later (HNDL) attacks — adversaries capturing data today to decrypt with future quantum computers
- Classic threats: cloud sync exposure, stolen drive, credential leak

**Goal:** A lightweight, shared Python utility providing quantum-safe encryption that all three projects can import.

---

## 2. Algorithm Selection

### Primary: ML-KEM-768 (FIPS 203, Security Level 3)

**Recommendation: ML-KEM-768** for all key encapsulation / asymmetric operations.

**Rationale:**

| Factor | ML-KEM-512 | **ML-KEM-768** | ML-KEM-1024 |
|---|---|---|---|
| NIST security level | 1 (AES-128 equivalent) | **3 (AES-192 equivalent)** | 5 (AES-256 equivalent) |
| Public key size | 800 bytes | **1,184 bytes** | 1,568 bytes |
| Performance | Fastest | **Excellent** | Slower |
| Recommendation | Minimum acceptable | **Best balance** | Overkill for local data |

ML-KEM-768 is the **de facto industry default** — chosen by Cloudflare, Google, Signal, and Apple for hybrid deployments. Security level 3 is appropriate for data that must remain confidential for 20+ years.

### Symmetric Layer: AES-256-GCM

Actual data encryption uses **AES-256-GCM** (authenticated encryption). ML-KEM establishes the shared secret; AES-256-GCM encrypts the data. This is standard hybrid encryption — KEM + DEM (Data Encapsulation Mechanism).

**Why not AES-128?** Grover's algorithm reduces symmetric key strength by half on a quantum computer: AES-128 → 64-bit effective security. AES-256 → 128-bit effective security (still strong). Always use AES-256 in a post-quantum context.

### Signatures: ML-DSA-65 (FIPS 204)

For any data that needs **integrity verification** (not just confidentiality), use ML-DSA-65 (security level 3, matching ML-KEM-768). This would apply to things like verifying backups or signed protocol documents.

### Hybrid Mode (Optional, Recommended for Production)

The OQS project recommends **hybrid cryptography**: combine ML-KEM-768 with classical X25519. This ensures the solution is at least as secure as current classical crypto even if an unforeseen flaw in ML-KEM emerges. For Tyler's local-only use case, pure ML-KEM-768 is acceptable given the threat model.

---

## 3. Architecture

### Where the Utility Lives

```
f:\executedcode\⊕Workspace\src\utils\quantum_safe_crypto.py
```

**Rationale:** ⊕Workspace is the designated home for cross-project shared utilities. All three projects already import from shared locations. Placing it here avoids code duplication and makes updates apply everywhere.

### Module Interface (Proposed)

```python
# f:\executedcode\⊕Workspace\src\utils\quantum_safe_crypto.py
#
# Quantum-safe encryption utility for Tyler's workspace.
# Backend: liboqs (ML-KEM-768) + AES-256-GCM
# DO NOT implement until liboqs is confirmed working in environment.

class QuantumSafeCrypto:
    """Hybrid KEM + symmetric encryption using ML-KEM-768 and AES-256-GCM."""

    def generate_keypair(self) -> tuple[bytes, bytes]:
        """Returns (public_key, private_key). Store private_key in key vault."""
        ...

    def encrypt(self, plaintext: bytes, recipient_public_key: bytes) -> bytes:
        """Encrypt plaintext for recipient. Returns ciphertext bundle."""
        ...

    def decrypt(self, ciphertext_bundle: bytes, private_key: bytes) -> bytes:
        """Decrypt ciphertext bundle using private key."""
        ...

    def encrypt_file(self, source_path: str, dest_path: str, public_key: bytes) -> None:
        """Encrypt a file in place."""
        ...

    def decrypt_file(self, source_path: str, dest_path: str, private_key: bytes) -> None:
        """Decrypt a file."""
        ...
```

### Ciphertext Bundle Format

```
[2 bytes: version] [4 bytes: KEM ciphertext length] [KEM ciphertext]
[12 bytes: AES-GCM nonce] [16 bytes: AES-GCM tag] [N bytes: encrypted payload]
```

This is self-describing — the bundle carries everything needed for decryption except the private key.

### Project Import Pattern

```python
# From any project:
import sys
sys.path.insert(0, r"f:\executedcode\⊕Workspace\src\utils")
from quantum_safe_crypto import QuantumSafeCrypto
```

---

## 4. Key Management

### Key Storage Location

```
f:\executedcode\⊕Workspace\src\data\keys\
    workspace.pub          # Public key (can be shared/backed up freely)
    workspace.priv         # Private key (NEVER commit to git, NEVER sync to cloud)
    workspace.priv.bak     # Encrypted backup copy (encrypted with a passphrase-derived key)
```

**Rules:**
- The `keys/` directory must be listed in `.gitignore` for `f:\executedcode\` repository
- Private key file permissions: read-only for Tyler's user account only (Windows: remove inherited permissions)
- The public key can be distributed freely — it's used to encrypt data, not decrypt it

### Key Derivation Alternative (Simpler)

Instead of managing a long-lived asymmetric keypair for local-only encryption, a simpler approach is **passphrase-derived symmetric encryption**:

- User supplies a passphrase once at session start
- Key derived via Argon2id (NIST-recommended KDF, quantum-resistant when paired with AES-256)
- No key files to manage; no risk of private key exposure
- **Downside:** Must enter passphrase each session; no automated background encryption

**Recommendation:** Use passphrase-derived encryption (Argon2id + AES-256-GCM) for the MVP. Graduate to ML-KEM-768 asymmetric keys when liboqs is confirmed working. Argon2id is available via `argon2-cffi` (pure Python, no native build required) and AES-256-GCM via Python's built-in `cryptography` package.

### Key Rotation

| Key type | Rotation policy |
|---|---|
| ML-KEM keypair | Annually, or on any suspected compromise |
| AES session keys | Per encryption operation (derived fresh each time from shared secret) |
| Passphrase-derived key | Never stored; rotation = changing the passphrase |

---

## 5. What to Protect vs. What's Fine in Plaintext

### Encrypt (High Priority)

| Asset | Location | Reason |
|---|---|---|
| IBM Quantum API token | Config file / env var | Credential; financial risk if exposed |
| Oura / Whoop / health API keys | ∞Life config | Credential |
| Health biomarker data | `infinitelife.db` selected tables | Personal health data — high sensitivity |
| Music royalty/financial data | ❤Music DB or CSV | Financial data |
| Quantum RNG cache | `ty_string_cache.txt` | Integrity matters; cache poisoning would corrupt randomness source |

### Fine in Plaintext

| Asset | Reason |
|---|---|
| Research markdown notes | No PII, no credentials |
| Algorithm implementations (.py) | Source code, not sensitive |
| Workout logs / supplement schedule | Low sensitivity (already public domain health info) |
| Music production session files | Not credentials |
| Agent definitions / prompts | Not credentials |

### Selective DB Encryption (∞Life)

Rather than encrypting the entire SQLite DB (which breaks all tooling), encrypt **specific column values** for high-sensitivity fields:
- `api_keys` table → encrypt `key_value` column
- `biomarkers` table → optionally encrypt `value` for most sensitive markers (e.g., bloodwork)
- Budget/financial tables → encrypt `amount`, `notes`

This preserves SQLite tooling while protecting sensitive fields.

---

## 6. Implementation Roadmap

### Phase 0: Prerequisites (Tyler action required)
1. Verify `cmake --version` works in Command Prompt
2. Verify Visual Studio Build Tools (C compiler) is installed
3. Confirm willingness to install `liboqs` native library

**If prerequisites are missing:** Implement Phase 1 first (no native dependencies), defer liboqs to Phase 2.

### Phase 1: MVP — Passphrase-Derived Encryption (No liboqs required)

```
Install (Tyler approval needed):
  C:\G\python.exe -m pip install cryptography argon2-cffi
```

Implement `quantum_safe_crypto.py` using:
- **Argon2id** (via `argon2-cffi`) for key derivation — quantum-resistant KDF
- **AES-256-GCM** (via `cryptography`) for authenticated encryption
- **Scope:** File encryption and selected SQLite column encryption

This is immediately deployable with a simple pip install. No native build required.

### Phase 2: Full PQC — ML-KEM-768 via liboqs

After Tyler confirms liboqs builds successfully:
1. Build liboqs from source (see `liboqs-assessment.md` for commands)
2. Install liboqs-python bindings
3. Replace Argon2id KDF with ML-KEM-768 key encapsulation in the module
4. Add ML-DSA-65 signatures for integrity verification of backups
5. Maintain backward compatibility with Phase 1 encrypted files via version byte in ciphertext bundle

### Phase 3: Selective DB Column Encryption (∞Life)

After Phase 1 or 2 is stable:
1. Add `encrypt_db_field()` / `decrypt_db_field()` helpers to the utility
2. Write migration script to encrypt existing sensitive values in `infinitelife.db`
3. Update `∞Life` read/write paths to decrypt on fetch

---

## 7. Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| liboqs native build fails on Tyler's machine | Medium | Phase 2 delayed | Phase 1 (pure Python) as fallback |
| Private key lost | Low | All encrypted data permanently inaccessible | Encrypted backup + passphrase escrow in password manager |
| Key file accidentally committed to git | Medium | Compromise | `.gitignore` rule + pre-commit hook |
| liboqs algorithm flaw discovered | Low | Encryption broken | Hybrid mode (ML-KEM + X25519); monitor OQS security advisories |
| Argon2id passphrase forgotten | Medium | Phase 1 data inaccessible | Store passphrase in password manager |

---

## 8. Immediate Recommendation

**Do not implement ML-KEM code yet.** The correct sequence:

1. **First:** Tyler confirms CMake + MSVC are available (or installs them)
2. **Then:** Test liboqs-python install in a scratch environment (`C:\G\python.exe -m pip install git+https://github.com/open-quantum-safe/liboqs-python`)
3. **If successful:** Proceed to Phase 2 implementation
4. **If blocked by build:** Proceed to Phase 1 (Argon2id + AES-256-GCM MVP) — this is genuinely quantum-safe for the symmetric layer and requires only `pip install`

The Phase 1 approach (Argon2id + AES-256-GCM) is **not a compromise** — it provides quantum-safe symmetric encryption today, with no native dependencies, while the ML-KEM asymmetric layer is being set up.

---

## 9. Files to Create (When Approved)

| File | Purpose |
|---|---|
| `f:\executedcode\⊕Workspace\src\utils\quantum_safe_crypto.py` | Main shared utility |
| `f:\executedcode\⊕Workspace\src\data\keys\.gitignore` | Prevent key files from being committed |
| `f:\executedcode\∞Life\src\utils\crypto_helpers.py` | ∞Life-specific wrappers for DB column encryption |
| `f:\executedcode\⟨ψ⟩Quantum\tests\test_quantum_safe_crypto.py` | Test suite for the utility |

---

## 10. Open Questions for Tyler

1. **Build tools:** Do you have CMake + Visual Studio Build Tools installed? (`cmake --version` in cmd)
2. **Phase preference:** Start with Phase 1 (pure Python, immediate) or wait for Phase 2 (ML-KEM, requires build)?
3. **Key model:** Prefer passphrase per session (no key files to manage) or asymmetric keypair (can automate encryption without passphrase prompts)?
4. **∞Life DB scope:** Which specific tables/columns in `infinitelife.db` should be encrypted first?
5. **Existing credentials:** Are IBM Quantum API token and health API keys currently in plaintext config files? If so, Phase 1 can protect those immediately.
