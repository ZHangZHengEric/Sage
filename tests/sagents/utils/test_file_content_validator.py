from sagents.utils.file_content_validator import FileContentValidator


def test_json_validation_passes_for_valid_json():
    result = FileContentValidator.validate("/tmp/sample.json", '{"name": "sage", "count": 1}')

    assert result["status"] == "passed"
    assert result["passed"] is True
    assert result["validator"] == "json"


def test_json_validation_reports_error_for_invalid_json():
    result = FileContentValidator.validate("/tmp/sample.json", '{"name": "sage",}')

    assert result["status"] == "error"
    assert result["passed"] is False
    assert "JSON 语法错误" in result["message"]


def test_yaml_validation_passes_for_valid_yaml():
    result = FileContentValidator.validate("/tmp/sample.yaml", "name: sage\ncount: 1\n")

    assert result["status"] == "passed"
    assert result["passed"] is True
    assert result["validator"] == "yaml"


def test_yaml_validation_reports_error_for_invalid_yaml():
    result = FileContentValidator.validate("/tmp/sample.yaml", "name: sage\n  count: 1\n")

    assert result["status"] == "error"
    assert result["passed"] is False
    assert "YAML 语法错误" in result["message"]


def test_python_validation_passes_for_valid_python():
    result = FileContentValidator.validate("/tmp/sample.py", "def hello():\n    return 1\n")

    assert result["status"] == "passed"
    assert result["passed"] is True
    assert result["validator"] == "python"


def test_python_validation_reports_error_for_invalid_python():
    result = FileContentValidator.validate("/tmp/sample.py", "def hello(\n    return 1\n")

    assert result["status"] == "error"
    assert result["passed"] is False
    assert "Python 语法错误" in result["message"]


def test_toml_validation_passes_for_valid_toml():
    result = FileContentValidator.validate("/tmp/sample.toml", "name = 'sage'\ncount = 1\n")

    assert result["status"] == "passed"
    assert result["passed"] is True
    assert result["validator"] == "toml"


def test_unsupported_extension_is_skipped():
    result = FileContentValidator.validate("/tmp/sample.md", "# title\n")

    assert result["status"] == "skipped"
    assert result["skipped"] is True
    assert result["passed"] is True
