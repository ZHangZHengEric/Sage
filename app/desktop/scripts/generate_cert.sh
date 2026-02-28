#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CERT_DIR="$SCRIPT_DIR/certs"
mkdir -p "$CERT_DIR"

CERT_NAME="SageAI Self Signed"
CERT_PASS="sage-password"

echo "Generating self-signed certificate..."

# Generate private key
if [ ! -f "$CERT_DIR/key.pem" ]; then
    openssl genrsa -out "$CERT_DIR/key.pem" 2048
fi

# Generate certificate request and self-signed certificate
if [ ! -f "$CERT_DIR/cert.pem" ]; then
    openssl req -new -key "$CERT_DIR/key.pem" -out "$CERT_DIR/csr.pem" \
        -subj "/CN=$CERT_NAME/C=CN/O=SageAI"

    openssl x509 -req -days 3650 -in "$CERT_DIR/csr.pem" \
        -signkey "$CERT_DIR/key.pem" -out "$CERT_DIR/cert.pem"
fi

# Export to P12
if [ ! -f "$CERT_DIR/cert.p12" ]; then
    openssl pkcs12 -export -out "$CERT_DIR/cert.p12" \
        -inkey "$CERT_DIR/key.pem" -in "$CERT_DIR/cert.pem" \
        -passout pass:"$CERT_PASS" \
        -name "$CERT_NAME"
fi

echo "Certificate generated at: $CERT_DIR/cert.p12"
echo "Password: $CERT_PASS"

# Convert to Base64 for Tauri (macos base64 behaves differently, ensure no newlines)
CERT_B64=$(base64 < "$CERT_DIR/cert.p12" | tr -d '\n')
echo "$CERT_B64" > "$CERT_DIR/cert.p12.base64"

echo "Base64 encoded certificate saved to: $CERT_DIR/cert.p12.base64"
