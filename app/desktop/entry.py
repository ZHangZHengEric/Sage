import sys
import os

# Fix SSL certificate verification for frozen (PyInstaller) builds
# This must be done before any SSL/TLS connections are made
if getattr(sys, 'frozen', False):
    # Running in a PyInstaller bundle
    bundle_dir = sys._MEIPASS if hasattr(sys, '_MEIPASS') else os.path.dirname(sys.executable)
    
    # Set SSL certificate paths for certifi
    certifi_cert_path = os.path.join(bundle_dir, '_internal', 'certifi', 'cacert.pem')
    if os.path.exists(certifi_cert_path):
        os.environ['SSL_CERT_FILE'] = certifi_cert_path
        os.environ['SSL_CERT_DIR'] = os.path.dirname(certifi_cert_path)
        os.environ['REQUESTS_CA_BUNDLE'] = certifi_cert_path
        os.environ['CURL_CA_BUNDLE'] = certifi_cert_path
    
    # Also try alternative paths
    alt_cert_path = os.path.join(os.path.dirname(sys.executable), '_internal', 'certifi', 'cacert.pem')
    if os.path.exists(alt_cert_path) and not os.environ.get('SSL_CERT_FILE'):
        os.environ['SSL_CERT_FILE'] = alt_cert_path
        os.environ['SSL_CERT_DIR'] = os.path.dirname(alt_cert_path)
        os.environ['REQUESTS_CA_BUNDLE'] = alt_cert_path
        os.environ['CURL_CA_BUNDLE'] = alt_cert_path

# Add project root to path
# We need to add the directory containing 'app' to sys.path
# 'entry.py' is in 'app/desktop/entry.py'
# so 'app' is in '../../' relative to 'entry.py'

current_dir = os.path.dirname(os.path.abspath(__file__))
# current_dir is .../app/desktop
project_root = os.path.abspath(os.path.join(current_dir, "../.."))
# project_root is .../Sage

if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Now we can import app.desktop.core.main
# This ensures that relative imports inside app.desktop.core work correctly
from app.desktop.core.main import main

if __name__ == "__main__":
    sys.exit(main())
