from pathlib import Path

from app.server_v2.services.package import server_v2_manifest
from tests.app.server_v2.conftest import make_settings


def test_package_has_no_yaml_credentials_or_model_routes():
    manifest = server_v2_manifest()
    assert manifest.credentials == {}
    assert manifest.models == {}
    assert manifest.entrypoint.agent == "main"
    assert manifest.interfaces["ag_ui"].plugin == "sage.protocol.ag-ui"
    assert manifest.runtime.capabilities == {}


def test_package_selects_mysql_and_otlp_from_host_settings(tmp_path: Path):
    manifest = server_v2_manifest(
        make_settings(
            tmp_path,
            mysql_url="mysql://sage:sage@127.0.0.1:3306/sage",
            jaeger_url="http://sage-jaeger:4317",
            jaeger_service_name="sage-server",
        )
    )
    session = manifest.runtime.capabilities["session.store"]
    assert session.plugin == "sage.session.mysql"
    assert session.config == {
        "dsn": "mysql://sage:sage@127.0.0.1:3306/sage",
        "table_prefix": "",
    }
    trace = manifest.runtime.capabilities["observability.trace-sink"]
    assert trace.plugin == "sage.trace.otlp"
    assert trace.config == {
        "endpoint": "http://sage-jaeger:4317",
        "service_name": "sage-server",
        "protocol": "grpc",
        "insecure": True,
    }


def test_package_skips_jaeger_when_endpoint_missing(tmp_path: Path):
    manifest = server_v2_manifest(
        make_settings(
            tmp_path,
            mysql_url="mysql://sage:sage@127.0.0.1:3306/sage",
        )
    )
    assert "observability.trace-sink" not in manifest.runtime.capabilities
    assert manifest.runtime.capabilities["session.store"].plugin == "sage.session.mysql"
