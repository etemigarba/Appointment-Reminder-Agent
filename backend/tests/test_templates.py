"""C4: template rendering (FR-7)."""

from datetime import UTC, datetime

from app.channels.templates import DEFAULT_TEMPLATE, render_reminder

START = datetime(2026, 9, 3, 14, 30, tzinfo=UTC)


def _render(template=None, name="Jane", title="Haircut"):
    return render_reminder(
        template=template,
        business_name="Test Salon",
        customer_name=name,
        appointment_title=title,
        start_at_utc=START,
    )


def test_default_template_used_when_none():
    text = _render(None)
    assert "2026-09-03" in text
    assert "14:30" in text
    assert "Test Salon" in text
    assert "Haircut" in text
    assert "STOP" in text


def test_custom_template_all_variables_substituted():
    text = _render("Hi {name}, {business} reminder for {title} on {date} at {time}!")
    assert text == "Hi Jane, Test Salon reminder for Haircut on 2026-09-03 at 14:30!"


def test_unknown_placeholder_left_untouched():
    text = _render("Hello {name}, see {nonsense_variable}")
    assert "{nonsense_variable}" in text
    assert "Jane" in text


def test_blank_template_falls_back_to_default():
    assert _render("") == _render(None)
    assert _render("   ") != ""


def test_render_never_raises_on_weird_input():
    text = _render("{name}{name}{name}", name=None)
    assert text == "theretherethere"
