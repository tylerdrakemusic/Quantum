from __future__ import annotations

from typing import Any


def build_openapi_document() -> dict[str, Any]:
    return {
        "openapi": "3.1.0",
        "info": {
            "title": "Quantum Randomness Service",
            "version": "1.0.0",
            "description": (
                "Authenticated bounded randomness primitives backed by verified "
                "quantum cache data with an OS CSPRNG fallback."
            ),
        },
        "servers": [{"url": "https://quantum-randomness.fly.dev"}],
        "security": [],
        "tags": [{"name": "Public"}, {"name": "Randomness"}],
        "paths": {
            "/health": {
                "get": {
                    "tags": ["Public"],
                    "summary": "Check service health",
                    "operationId": "health",
                    "responses": {"200": {"$ref": "#/components/responses/Health"}},
                }
            },
            "/v1/status": {
                "get": {
                    "tags": ["Public"],
                    "summary": "Read cache provenance status",
                    "operationId": "status",
                    "responses": {"200": {"$ref": "#/components/responses/Status"}},
                }
            },
            "/openapi.json": {
                "get": {
                    "tags": ["Public"],
                    "summary": "Read this OpenAPI contract",
                    "operationId": "openapi",
                    "responses": {"200": {"$ref": "#/components/responses/OpenAPI"}},
                }
            },
            "/docs": {
                "get": {
                    "tags": ["Public"],
                    "summary": "Open the interactive API documentation",
                    "operationId": "docs",
                    "responses": {"200": {"$ref": "#/components/responses/SwaggerUI"}},
                }
            },
            "/setup": {
                "get": {
                    "tags": ["Public"],
                    "summary": "Read the operator setup guide",
                    "operationId": "setup",
                    "responses": {"200": {"$ref": "#/components/responses/SetupGuide"}},
                }
            },
            "/v1/bytes": {
                "get": {
                    "tags": ["Randomness"],
                    "summary": "Generate random bytes",
                    "operationId": "randomBytes",
                    "security": [{"bearerAuth": []}],
                    "parameters": [{"$ref": "#/components/parameters/ByteCount"}],
                    "responses": _randomness_responses(
                        "#/components/schemas/BytesSuccess"
                    ),
                }
            },
            "/v1/bits": {
                "get": {
                    "tags": ["Randomness"],
                    "summary": "Generate random bits",
                    "operationId": "randomBits",
                    "security": [{"bearerAuth": []}],
                    "parameters": [{"$ref": "#/components/parameters/BitCount"}],
                    "responses": _randomness_responses(
                        "#/components/schemas/BitsSuccess"
                    ),
                }
            },
            "/v1/ints": {
                "get": {
                    "tags": ["Randomness"],
                    "summary": "Generate a random integer in an inclusive range",
                    "operationId": "randomInteger",
                    "security": [{"bearerAuth": []}],
                    "parameters": [
                        {"$ref": "#/components/parameters/Minimum"},
                        {"$ref": "#/components/parameters/Maximum"},
                    ],
                    "responses": _randomness_responses(
                        "#/components/schemas/IntegerSuccess"
                    ),
                }
            },
            "/v1/bool": {
                "get": {
                    "tags": ["Randomness"],
                    "summary": "Generate a random boolean",
                    "operationId": "randomBoolean",
                    "security": [{"bearerAuth": []}],
                    "responses": _randomness_responses(
                        "#/components/schemas/BooleanSuccess"
                    ),
                }
            },
        },
        "components": {
            "securitySchemes": {
                "bearerAuth": {
                    "type": "http",
                    "scheme": "bearer",
                    "bearerFormat": "opaque service token",
                }
            },
            "parameters": {
                "ByteCount": {
                    "name": "n",
                    "in": "query",
                    "required": False,
                    "description": "Number of bytes, from 1 through 1024.",
                    "schema": {"type": "integer", "minimum": 1, "maximum": 1024, "default": 1},
                },
                "BitCount": {
                    "name": "n",
                    "in": "query",
                    "required": False,
                    "description": "Number of bits, from 1 through 8192.",
                    "schema": {"type": "integer", "minimum": 1, "maximum": 8192, "default": 1},
                },
                "Minimum": {
                    "name": "min",
                    "in": "query",
                    "required": True,
                    "description": "Inclusive lower bound.",
                    "schema": {"type": "integer"},
                },
                "Maximum": {
                    "name": "max",
                    "in": "query",
                    "required": True,
                    "description": "Inclusive upper bound; range width is at most 2^31.",
                    "schema": {"type": "integer"},
                },
            },
            "schemas": {
                "Health": {
                    "type": "object",
                    "required": ["status"],
                    "properties": {"status": {"type": "string", "const": "ok"}},
                },
                "Provenance": {
                    "type": "object",
                    "required": ["source"],
                    "properties": {
                        "source": {"type": "string", "enum": ["quantum", "os_csprng"]},
                        "quantum_cache": {
                            "type": "string",
                            "enum": ["current", "stale", "unavailable"],
                        },
                    },
                },
                "Status": {
                    "type": "object",
                    "required": ["service", "provenance"],
                    "properties": {
                        "service": {"type": "string", "const": "quantum-randomness"},
                        "provenance": {"$ref": "#/components/schemas/Provenance"},
                    },
                },
                "BytesSuccess": {
                    "type": "object",
                    "required": ["bytes_hex", "provenance"],
                    "properties": {
                        "bytes_hex": {"type": "string", "pattern": "^[0-9a-f]+$"},
                        "provenance": {"$ref": "#/components/schemas/Provenance"},
                    },
                },
                "BitsSuccess": {
                    "type": "object",
                    "required": ["bits", "provenance"],
                    "properties": {
                        "bits": {"type": "string", "pattern": "^[01]+$"},
                        "provenance": {"$ref": "#/components/schemas/Provenance"},
                    },
                },
                "IntegerSuccess": {
                    "type": "object",
                    "required": ["value", "provenance"],
                    "properties": {
                        "value": {"type": "integer"},
                        "provenance": {"$ref": "#/components/schemas/Provenance"},
                    },
                },
                "BooleanSuccess": {
                    "type": "object",
                    "required": ["value", "provenance"],
                    "properties": {
                        "value": {"type": "boolean"},
                        "provenance": {"$ref": "#/components/schemas/Provenance"},
                    },
                },
                "Error": {
                    "type": "object",
                    "required": ["error"],
                    "properties": {"error": {"type": "string"}},
                },
            },
            "responses": {
                "Health": {
                    "description": "Service is reachable.",
                    "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Health"}}},
                },
                "Status": {
                    "description": "Public cache provenance status.",
                    "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Status"}}},
                },
                "OpenAPI": {
                    "description": "The public OpenAPI 3.1 contract.",
                    "content": {"application/json": {"schema": {"type": "object"}}},
                },
                "SwaggerUI": {
                    "description": "Interactive Swagger UI HTML.",
                    "content": {"text/html": {"schema": {"type": "string"}}},
                },
                "SetupGuide": {
                    "description": "Documentation-only operator setup guide.",
                    "content": {"text/markdown": {"schema": {"type": "string"}}},
                },
            },
        },
    }


def _randomness_responses(success_schema: str) -> dict[str, Any]:
    return {
        "200": {
            "description": "Generated value and its source provenance.",
            "content": {"application/json": {"schema": {"$ref": success_schema}}},
        },
        "400": {
            "description": "Query validation failed.",
            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}},
        },
        "401": {
            "description": "Bearer authentication failed.",
            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}},
        },
        "413": {
            "description": "Requested value exceeds the endpoint limit.",
            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}},
        },
        "429": {
            "description": "Per-token rate limit exceeded: 10 requests per minute or 1 MiB per hour.",
            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}},
        },
    }


SWAGGER_UI_HTML = """<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>Quantum Randomness API</title>
<link rel="stylesheet" href="https://unpkg.com/swagger-ui-dist@5/swagger-ui.css"></head>
<body><div id="swagger-ui"></div>
<script src="https://unpkg.com/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
<script>window.ui = SwaggerUIBundle({url: '/openapi.json', dom_id: '#swagger-ui'});</script>
</body></html>"""