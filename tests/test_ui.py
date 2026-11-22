from pathlib import Path
from streamlit.testing.v1 import AppTest


def test_real_stdio_ui_and_required_measurements():
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "streamlit_app.py"), default_timeout=30).run()
    app.button[1].click().run()
    assert not app.exception
    assert len(app.number_input) == 2
    assert all(x.value is None for x in app.number_input)
    app.checkbox[0].check()
    app.button[2].click().run()
    assert any("обязательное поле" in x.value for x in app.error)
    app.number_input[0].set_value(70.0)
    app.number_input[1].set_value(175.0)
    app.button[2].click().run()
    assert not app.exception
    assert "22.86" in app.metric[0].value
