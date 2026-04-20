# Heisenberg Uncertainty Principle as Quantum-Ready Encryption Candidate

**Research Date:** 2026-04-18  
**Scope:** ⟨ψ⟩Quantum project — quantum cryptography research  
**Status:** Research-stage analysis (not implementation-ready)

---

## 1. Overview

The Heisenberg Uncertainty Principle (HUP) states that certain pairs of physical observables — most famously position/momentum and polarization bases — cannot both be measured to arbitrary precision simultaneously. Measuring one observable disturbs the conjugate observable irreversibly. This is not a limitation of instruments; it is a fundamental feature of quantum mechanics enforced by the mathematics of non-commuting operators.

This property has direct cryptographic relevance: **any eavesdropper who intercepts and measures a quantum channel necessarily disturbs it**, leaving detectable traces. This physical impossibility of passive interception is the foundation of quantum key distribution (QKD).

---

## 2. HUP and Quantum Key Distribution (BB84)

### How HUP Underpins BB84

BB84 (Bennett & Brassard, 1984) is the canonical QKD protocol and directly exploits HUP:

1. **Alice** encodes bits as photon polarizations in one of two conjugate bases: rectilinear (0°/90°) or diagonal (45°/135°).
2. **Bob** randomly chooses a measurement basis for each photon.
3. **Eve** cannot measure in the correct basis every time without guessing — if she measures in the wrong basis, she collapses the quantum state and introduces errors.
4. **Error rate check:** Alice and Bob compare a subset of bits over a classical authenticated channel. An error rate above ~11% (for individual-qubit attacks) signals eavesdropping. The protocol aborts or applies privacy amplification.

The security guarantee is rooted in:
- **No-cloning theorem** (consequence of HUP): Eve cannot copy an unknown quantum state.
- **Measurement disturbance**: any measurement in the wrong basis irreversibly alters polarization state.
- **Information-disturbance tradeoff** (Heisenberg-derived): extracting information from a quantum channel requires causing disturbance detectable by the legitimate parties.

### Evidence Quality: BB84 Security

| Claim | Status |
|---|---|
| BB84 is information-theoretically secure against arbitrary attacks (unconditional security) | **Theoretically proven** — Mayers (1996), Lo & Chau (1999), Shor & Preskill (2000). Proofs require perfect devices. |
| HUP causes eavesdropping disturbance | **Proven from quantum mechanics axioms** — not empirical |
| Practical QKD systems achieve claimed security | **Partially demonstrated** — real systems have side channels (timing, power, detector blinding attacks). Security depends heavily on device characterization. |
| BB84 is secure against quantum computers | **Yes** — the security is information-theoretic, not computational. A quantum computer cannot retroactively decrypt captured ciphertext without having access to the raw photons. |

---

## 3. Is HUP a Viable Post-Quantum Encryption Primitive?

### Short Answer

**No — not as an encryption primitive. It is a key distribution primitive.**

HUP/QKD provides **quantum-safe key agreement**, not encryption. After the quantum channel establishes a shared secret key, classical symmetric encryption (e.g., AES-256) is used for the actual data. The confusion arises because QKD is often marketed as "quantum encryption."

### Technical Distinction

| Concept | What It Provides | Example |
|---|---|---|
| QKD (HUP-based) | Secure key agreement over an untrusted quantum channel | BB84, E91, B92 |
| Post-Quantum Cryptography (PQC) | Classical algorithms hard for quantum computers to break | ML-KEM, ML-DSA, SPHINCS+ |
| Quantum encryption | **Does not exist as a standalone primitive** — this term describes QKD + symmetric encryption |

HUP does not directly provide:
- **Authenticated encryption** (you still need a classical MAC or digital signature)
- **Public-key encryption** (QKD requires a pre-shared authentication secret to prevent man-in-the-middle)
- **Scalable encryption** (each QKD session requires a dedicated quantum channel between parties)

### Why QKD ≠ Post-Quantum Encryption

PQC (e.g., CRYSTALS-Kyber → ML-KEM) is a **software algorithm** running on classical hardware, resistant to quantum attacks. QKD requires:
- Dedicated photon-level quantum hardware (quantum optical fiber, single-photon detectors)
- Line-of-sight or fiber-optic quantum channels (range-limited, ~100-400 km without quantum repeaters)
- A classical authenticated side-channel for key reconciliation

For Tyler's workspace (protecting SQLite DBs, music catalog files, local data), **QKD is not applicable**. The relevant technology is PQC.

---

## 4. Candidate Status Assessment

### HUP / QKD as a Cryptographic Primitive

| Dimension | Assessment |
|---|---|
| Theoretical maturity | **Very high** — unconditional security proofs exist since 1996-2000 |
| Experimental demonstration | **High** — commercial QKD systems exist (ID Quantique, Toshiba, MagiQ). Satellite QKD demonstrated (Micius satellite, 2017). |
| Practical deployment readiness | **Low for software-only environments** — requires quantum hardware |
| Relevance to Tyler's workspace | **Not applicable** — workspace is classical local hardware |
| Quantum computer resistance | **Yes** — but irrelevant without quantum channel hardware |

### What HUP-based Cryptography Is Good For

- **Telecom/government backbone links** where quantum fiber is deployed
- **Long-term key establishment** for ultra-high-security scenarios
- **Academic/research context** within ⟨ψ⟩Quantum for algorithm study and simulation

---

## 5. Relationship to Existing ⟨ψ⟩Quantum Work

The project already has `research/quantum_qkd_bb84.py` — a simulation of BB84. This correctly positions QKD as a research topic. The simulation demonstrates HUP-driven eavesdropping detection in software, but this is **not** a deployable encryption tool (there is no physical quantum channel).

The existing BB84 implementation is valuable for:
- Demonstrating the protocol's mechanics
- Teaching the principles
- Potentially generating demonstration material

It is **not** a substitute for software PQC for data protection.

---

## 6. Summary & Recommendation

- **HUP is foundational** to quantum cryptography but operates at the key distribution layer, not the encryption layer.
- **BB84 security is theoretically proven** and information-theoretically secure — the strongest possible guarantee.
- **Not a viable encryption primitive** for Tyler's workspace — requires quantum hardware unavailable here.
- **For workspace data protection**, PQC algorithms (ML-KEM, ML-DSA) are the correct approach — see `liboqs-assessment.md` and `quantum-safe-encryption-design.md`.
- **For ⟨ψ⟩Quantum research value**: the existing BB84 simulation is a solid foundation; consider extending it with eavesdropping simulation and privacy amplification steps.

---

## 7. References

- Bennett, C. H. & Brassard, G. (1984). Quantum cryptography: public key distribution and coin tossing. *Proceedings of IEEE International Conference on Computers, Systems and Signal Processing*, 175–179.
- Mayers, D. (1996). Quantum key distribution and string oblivious transfer in noisy channels. *CRYPTO 1996*.
- Shor, P. W. & Preskill, J. (2000). Simple proof of security of the BB84 quantum key distribution protocol. *Physical Review Letters*, 85(2), 441.
- Lo, H.-K. & Chau, H. F. (1999). Unconditional security of quantum key distribution over arbitrarily long distances. *Science*, 283(5410), 2050–2056.
- Lütkenhaus, N. (2000). Security against individual attacks for realistic quantum key distribution. *Physical Review A*, 61(5).
- NIST IR 8413 (2022). Status report on the third round of the NIST Post-Quantum Cryptography standardization process.
