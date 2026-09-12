from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_chat_uses_processing_state_and_rerenders_completed_turn():
    source = (ROOT / "streamlit_app.py").read_text(encoding="utf-8")
    assert 'processing_key = f"vg_ask_processing_{token}"' in source
    assert 'st.session_state[processing_key] = question' in source
    assert 'processing_question = st.session_state.get(processing_key)' in source
    assert 'composer returns below the newest answer' in source
    assert 'st.rerun()' in source


def test_chat_end_marker_is_rendered_after_chat_input():
    source = (ROOT / "streamlit_app.py").read_text(encoding="utf-8")
    input_pos = source.index('typed_question = st.chat_input(')
    marker_pos = source.index('_chat_end_marker(st, token)', input_pos)
    assert marker_pos > input_pos
