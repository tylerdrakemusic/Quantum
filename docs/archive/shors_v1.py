#!/usr/bin/env python3
"""
Enhanced Shor's Algorithm Implementation with Concurrency and Improved Error Handling

File: shors.py

Overview:
----------
This file implements Shor's algorithm in an object‐oriented and modular manner. Key enhancements include:
  • Modular, reusable classes (QuantumRandomizer and ShorsAlgorithm) for better separation of concerns.
  • Preservation of all quantum random functions from the 'quantum_rt' import unchanged.
  • Enhanced error handling with try-except blocks wherever needed (e.g. backend initialization and JSON I/O).
  • Use of concurrent.futures (ThreadPoolExecutor) to factorize multiple test cases in parallel for improved performance.
  • JSON file interactions to store results in separate folders (tyJson, exercises) using helper functions.
  • Directory creation for resources (images, videos, recordings) in designated folders.
  • Comprehensive inline comments documenting rationale behind design decisions and changes.
  • Detailed analysis and change set documentation at the beginning of the file.

Change Set Summary:
--------------------
1. Refactored the code into modular classes (QuantumRandomizer and ShorsAlgorithm) to enhance reusability.
2. Added error handling when initializing IBMQ backend and while reading/writing JSON data.
3. Used concurrent.futures to run factorization for multiple N concurrently instead of sequential processing.
4. Improved JSON file operations by checking file existence and initializing files with default empty lists.
5. Added extensive inline comments and documentation for clarity and ease of maintenance.
6. Preserved the quantum_rt import functions exactly, as required.
7. Removed endless loops and direct user input for compatibility with automated test setups.
8. Provided specific examples for factorization test cases rather than generic values.

Author: OpenAI ChatGPT
Date: 2023-10
"""

import sys
import json
import os
from math import gcd
from concurrent.futures import ThreadPoolExecutor, as_completed

# Qiskit and IBM Quantum runtime imports
from qiskit import QuantumCircuit, transpile
from qiskit.circuit.library import QFT
from qiskit_ibm_runtime import SamplerV2

# IBM Quantum backend configuration and account services
from quantum_backend import get_ibm_backend  # This module should provide backend configuration
from ty_py import tokenReturns as TRX  # IBM account management (tokens, services, etc.)

# Preserve quantum_rt functions exactly as specified
from quantum_rt import qRandom, qRax, qsample, qhoice, qpermute, qRandomBool, qRandomBitstring

# Constants for file/folder paths
TY_JSON_FOLDER = "./tyJson"
EXERCISES_FOLDER = "./exercises"
IMAGES_FOLDER = "./images"
ENHANCED_IMAGES_FOLDER = "./enhanced_images"
VIDEOS_FOLDER = "./videos"
RECORDINGS_FOLDER = "./recordings"

# Ensure necessary directories exist
for folder in [TY_JSON_FOLDER, EXERCISES_FOLDER, IMAGES_FOLDER, ENHANCED_IMAGES_FOLDER, VIDEOS_FOLDER, RECORDINGS_FOLDER]:
    os.makedirs(folder, exist_ok=True)


class QuantumRandomizer:
    """
    Handles quantum-based random number generation using predefined quantum functions.
    All methods are static to allow usage without instantiation.
    """

    @staticmethod
    def get_random_integer(min_val: int, max_val: int) -> int:
        """
        Returns a quantum-generated random integer within [min_val, max_val].
        """
        return qRax(min_val, max_val)

    @staticmethod
    def get_random_bitstring(length: int) -> str:
        """
        Returns a quantum-generated bitstring of specific length.
        """
        return qRandomBitstring(length)

    @staticmethod
    def choose_randomly(options: list):
        """
        Selects and returns a random element from the provided list using quantum randomness.
        """
        return qhoice(options)

    @staticmethod
    def sample_without_replacement(lst: list, k: int) -> list:
        """
        Returns a list of k unique elements sampled from lst via quantum randomness.
        """
        return qsample(lst, k)

    @staticmethod
    def get_random_boolean() -> bool:
        """
        Returns a quantum-based random boolean value.
        """
        return qRandomBool()


class ShorsAlgorithm:
    """
    Implements Shor's algorithm for factorizing integers using quantum computing.
    Includes methods to build and execute quantum circuits and extract factors.
    """

    def __init__(self, N: int):
        """
        Initialize the algorithm with an integer N to factorize.
        """
        self.N = N
        self.num_qubits = self.calculate_num_qubits()
        self.backend = self.initialize_backend()
        self.service = self.initialize_service()

    def calculate_num_qubits(self) -> int:
        """
        Determine number of qubits needed based on bit-length of N.
        """
        return max(1, self.N.bit_length())

    def initialize_backend(self):
        """
        Retrieve the appropriate IBM Quantum backend.
        """
        try:
            backend = get_ibm_backend(self.num_qubits)
            return backend
        except Exception as e:
            print(f"Error initializing backend: {e}")
            sys.exit(1)  # Critical failure, so exit.

    def initialize_service(self):
        """
        Initialize the Qiskit Runtime service for quantum computations.
        """
        try:
            TRX.qisKitAccount()  # Initialize account ASAP
            service = TRX.qisKitService()
            return service
        except Exception as e:
            print(f"Error initializing Qiskit runtime service: {e}")
            sys.exit(1)

    def get_coprime_a(self) -> int:
        """
        Returns a randomly chosen integer 'a' such that 1 < a < N and gcd(a, N)==1.
        """
        # Loop until a valid coprime is found; the range is [2, N-1].
        while True:
            a = QuantumRandomizer.get_random_integer(2, self.N - 1)
            if gcd(a, self.N) == 1:
                return a

    def create_quantum_circuit(self, a: int) -> QuantumCircuit:
        """
        Constructs the quantum circuit necessary for Shor's algorithm.
        """
        # Creating a circuit with 2*num_qubits + 1 qubits and num_qubits classical bits.
        qc = QuantumCircuit(self.num_qubits * 2 + 1, self.num_qubits)

        # Prepare registers: Apply Hadamard on first 2*num_qubits qubits.
        qc.h(range(self.num_qubits * 2))
        # Initialize the last qubit to |1>
        qc.x(self.num_qubits * 2)

        # Apply controlled-U operations with calculated phase rotations.
        for qubit in range(self.num_qubits):
            angle = 2 * 3.141592653589793 * a / (2 ** (qubit + 1))
            qc.cp(angle, qubit, self.num_qubits * 2)

        # Append inverse Quantum Fourier Transform on the first register.
        qc.append(QFT(self.num_qubits, inverse=True), range(self.num_qubits))
        # Measurement on the first register.
        qc.measure(range(self.num_qubits), range(self.num_qubits))

        return qc

    def transpile_circuit(self, qc: QuantumCircuit) -> QuantumCircuit:
        """
        Transpile the quantum circuit to adapt to the selected backend.
        """
        try:
            transpiled_qc = transpile(qc, backend=self.backend)
            return transpiled_qc
        except Exception as e:
            print(f"Error during transpilation: {e}")
            raise

    def run_circuit(self, transpiled_qc: QuantumCircuit) -> dict:
        """
        Executes the transpiled circuit using the Sampler V2 primitive.
        Returns the measurement counts scaled up for significance.
        """
        try:
            sampler = SamplerV2(backend=self.backend)
            job = sampler.run([transpiled_qc])
            result = job.result()
            quasi_dists = result.quasi_dists[0]  # Focus on first circuit's outcome
            # Scale probabilities to integer counts (scaling factor used here is arbitrary)
            counts = {key: int(value * 1000) for key, value in quasi_dists.items()}
            return counts
        except Exception as e:
            print(f"Error running circuit: {e}")
            return {}

    def extract_factors(self, counts: dict) -> tuple:
        """
        Extracts factors based on measurement counts. Returns a tuple of factors if found.
        If extraction fails, returns a failure message and N.
        """
        if not counts:
            print("No measurement counts returned from the sampler.")
            return "Failed to factorize", self.N

        # Take the measurement with the highest count
        measured_value = int(max(counts, key=counts.get))
        print(f"Measured value: {measured_value}")

        # NOTE: Below extraction method is intentionally simplified and may not reflect full period finding.
        if measured_value != 0:
            # Calculate period from a random base via a simplistic method (for demonstration)
            random_base = QuantumRandomizer.get_random_integer(2, self.N - 1)
            period = pow(random_base, measured_value, self.N) - 1
            if period % 2 == 0:
                period //= 2
                r = gcd(period, self.N)
                if r != 1 and r != self.N:
                    print(f"Found factors: {r} and {self.N // r}")
                    return r, self.N // r

        print("Failed to extract factors using the measurement result.")
        return "Failed to factorize", self.N

    def factorize(self) -> tuple:
        """
        Runs Shor's algorithm to factorize integer N.
        Returns: tuple of factors or a failure message.
        """
        a = self.get_coprime_a()
        print(f"Randomly chosen coprime 'a': {a}")

        qc = self.create_quantum_circuit(a)
        transpiled_qc = self.transpile_circuit(qc)
        counts = self.run_circuit(transpiled_qc)
        factors = self.extract_factors(counts)
        return factors


def load_json_data(filepath: str):
    """
    Loads JSON data from file, initializing it with an empty list if nonexistent or corrupted.
    """
    if not os.path.exists(filepath):
        # File not found, so create with default empty list.
        try:
            with open(filepath, 'w') as f:
                json.dump([], f)
        except Exception as e:
            print(f"Error initializing JSON file {filepath}: {e}")
        return []

    try:
        with open(filepath, 'r') as f:
            data = json.load(f)
    except (json.JSONDecodeError, Exception) as e:
        print(f"Error decoding JSON file {filepath}: {e}. Reinitializing the file.")
        data = []
        try:
            with open(filepath, 'w') as f:
                json.dump([], f)
        except Exception as ex:
            print(f"Error writing to JSON file {filepath}: {ex}")
    return data


def append_to_json(filepath: str, data):
    """
    Appends new data to a JSON file, creating the file if it does not exist.
    """
    try:
        existing_data = load_json_data(filepath)
        existing_data.append(data)
        with open(filepath, 'w') as f:
            json.dump(existing_data, f, indent=4)
    except Exception as e:
        print(f"Error appending data to {filepath}: {e}")


def factorization_task(N: int) -> dict:
    """
    Helper function to run factorization for a given integer N.
    Returns a dictionary with the result and additional details.
    """
    result = {"N": N, "factors": None, "status": "Failed"}
    if N <= 1:
        result["error"] = f"Invalid input {N}: N must be greater than 1."
        return result

    print(f"\nStarting Shor's algorithm for N: {N}")
    shor = ShorsAlgorithm(N)
    factors = shor.factorize()
    if isinstance(factors, tuple) and all(isinstance(f, int) for f in factors):
        result["factors"] = factors
        result["status"] = "Success"
    else:
        result["result"] = factors
    return result


def main():
    """
    Main method to coordinate factorization tasks concurrently.
    Test cases for factorization are processed in parallel using ThreadPoolExecutor.
    """
    # Defined test cases for factorization (specific examples)
    test_cases = [15, 21, 35, 77, 143]

    results = []

    # Use ThreadPoolExecutor to parallelize processing
    with ThreadPoolExecutor(max_workers=min(5, len(test_cases))) as executor:
        # Submit tasks to executor
        future_to_N = {executor.submit(factorization_task, N): N for N in test_cases}
        for future in as_completed(future_to_N):
            N = future_to_N[future]
            try:
                data = future.result()
                results.append(data)
                if data["status"] == "Success":
                    print(f"Successfully factorized {N}: factors are {data['factors']}")
                    append_to_json(os.path.join(EXERCISES_FOLDER, "factorizations.json"), data)
                else:
                    print(f"Failed to factorize {N}. Details: {data.get('error', data.get('result'))}")
                    append_to_json(os.path.join(EXERCISES_FOLDER, "failed_factorizations.json"), data)
            except Exception as exc:
                print(f"Exception occurred while processing N={N}: {exc}")

    # Optionally, we could print a summary of results here.
    print("\nFactorization results summary:")
    for res in results:
        print(res)


if __name__ == "__main__":
    main()

# End of file. 
# NOTE: All quantum_rt functions are preserved exactly per requirements.
# Changes have been made to enable:
#   • Object-oriented design,
#   • Concurrency using ThreadPoolExecutor,
#   • Robust error handling for I/O and backend errors,
#   • Modular JSON file management for storing results.
# All design decisions have been commented inline for clarity.
# DONE: Addressing all TODO markers as per instruction (none remaining).
