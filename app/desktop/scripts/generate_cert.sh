#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CERT_DIR="$SCRIPT_DIR/certs"
mkdir -p "$CERT_DIR"

# Check if existing certificate has Code Signing extension
if [ -f "$CERT_DIR/cert.pem" ]; then
    if ! openssl x509 -in "$CERT_DIR/cert.pem" -text -noout | grep -q "Code Signing"; then
        echo "Existing certificate lacks Code Signing extension. Regenerating..."
        rm -f "$CERT_DIR/cert.pem" "$CERT_DIR/cert.p12" "$CERT_DIR/cert.p12.base64" "$CERT_DIR/csr.pem"
    fi
fi

CERT_NAME="SageAI Self Signed"
CERT_PASS="sage-password"

echo "Generating self-signed certificate..."

# Create OpenSSL config file for code signing extensions
cat > "$CERT_DIR/openssl.cnf" <<EOF
[req]
distinguished_name = req_distinguished_name
x509_extensions = v3_req
prompt = no

[req_distinguished_name]
CN = $CERT_NAME
C = CN
O = SageAI

[v3_req]
keyUsage = critical, digitalSignature, keyEncipherment
extendedKeyUsage = codeSigning
subjectAltName = @alt_names

[alt_names]
DNS.1 = sage.ai
EOF

# Generate private key
if [ ! -f "$CERT_DIR/key.pem" ]; then
    openssl genrsa -out "$CERT_DIR/key.pem" 2048
fi

# Generate certificate request and self-signed certificate with extensions
if [ ! -f "$CERT_DIR/cert.pem" ]; then
    openssl req -new -key "$CERT_DIR/key.pem" -out "$CERT_DIR/csr.pem" \
        -config "$CERT_DIR/openssl.cnf"

    openssl x509 -req -days 3650 -in "$CERT_DIR/csr.pem" \
        -signkey "$CERT_DIR/key.pem" -out "$CERT_DIR/cert.pem" \
        -extensions v3_req -extfile "$CERT_DIR/openssl.cnf"
fi

# Export to P12
if [ ! -f "$CERT_DIR/cert.p12" ]; then
    openssl pkcs12 -export -legacy -out "$CERT_DIR/cert.p12" \
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

# Cleanup
rm "$CERT_DIR/openssl.cnf"
