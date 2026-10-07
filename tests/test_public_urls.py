from shared.public_urls import codespaces_peer_url


def test_codespaces_forwarded_urls_use_port_in_hostname():
    gui='https://effective-fishstick-r5vxqpp64w43pgxw-8501.app.github.dev/'
    agent=codespaces_peer_url(gui,8501,8081)
    assert agent=='https://effective-fishstick-r5vxqpp64w43pgxw-8081.app.github.dev'
    assert codespaces_peer_url(agent,8081,8501)==gui.rstrip('/')
    assert codespaces_peer_url('http://localhost:8501',8501,8081) is None
