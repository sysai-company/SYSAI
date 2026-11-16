from app.net import installer


def test_agent_installer_has_official_hermes_github_fallback():
    script = installer.script("https://sysai.example")

    primary = "https://hermes-agent.nousresearch.com/install.ps1"
    fallback = "https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.ps1"

    assert primary in script
    assert fallback in script
    assert script.index(primary) < script.index(fallback)
    assert "Invoke-WebRequest -Uri $source.Url -UseBasicParsing -ErrorAction Stop" in script
    assert "Hermes Agent bootstrap:" in script
    assert "не удалось загрузить официальный установщик Hermes" in script
