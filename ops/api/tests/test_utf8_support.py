"""Test UTF-8 support for non-ASCII content."""


def test_urgency_rules_with_devanagari(client, test_settings):
    """GET /v1/urgency-rules should return Devanagari text intact without -X utf8."""
    response = client.get(
        "/v1/urgency-rules",
        headers={"X-Service-Key": test_settings.service_key}
    )
    assert response.status_code == 200
    
    data = response.json()
    
    # Verify structure
    assert "safety_lexicon" in data
    assert "self_harm" in data["safety_lexicon"]
    
    # Check for Devanagari characters (should be preserved)
    # urgency_rules.yaml contains: "बेहोश", "रैगिंग", "आत्महत्या", "मारपीट", "धमकी"
    self_harm_terms = data["safety_lexicon"]["self_harm"]
    
    # Convert to string for searching
    self_harm_str = str(self_harm_terms)
    
    # At least one Devanagari term should be present
    devanagari_found = any([
        "बेहोश" in self_harm_str,
        "रैगिंग" in self_harm_str,
        "आत्महत्या" in self_harm_str,
        "मारपीट" in self_harm_str,
        "धमकी" in self_harm_str
    ])
    
    assert devanagari_found, f"No Devanagari text found in safety_lexicon: {self_harm_str}"
