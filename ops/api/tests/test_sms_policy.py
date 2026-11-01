"""SMS policy: one test per suppression reason plus positive cases (pure functions, no app)."""
from pathlib import Path

import pytest
import yaml
from resolvix_contracts import DepartmentsConfig

from resolvix_ops.sms import policy

CONFIG_DIR = Path(__file__).parent.parent.parent.parent / "contracts" / "config"
CFG = policy.load_sms_config(CONFIG_DIR / "sms_templates.yaml")
DEPTS = DepartmentsConfig.model_validate(yaml.safe_load((CONFIG_DIR / "departments.yaml").read_text(encoding="utf-8")))
STAFF = policy.staff_alert_numbers(DEPTS)

CALLER = "+919000000004"


def run(template_id, consent, variables, to=CALLER, cfg=CFG):
    return policy.evaluate(cfg, STAFF, template_id=template_id, consent=consent, to_number=to, variables=variables)


GOOD = {
    "ticket_created": ("transactional", {"ticket_id": "HS-1044", "dept": "Hostel Office"}),
    "status_change": ("transactional", {"ticket_id": "HS-1044", "status": "in progress"}),
    "answer_copy": ("caller_requested", {"summary": "Hostel curfew is 10 PM on weekdays.", "source": "Hostel Rules",
                                         "url": "https://college.example/hostel/rules"}),
    "staff_alert": ("staff", {"ticket_id": "EX-1001", "summary": "Student cannot find exam room; paper in 15 minutes."}),
}


# ------------------------------------------------------------------ positives
@pytest.mark.parametrize("template_id", sorted(GOOD))
def test_each_template_passes_with_reasonable_vars(template_id):
    consent, variables = GOOD[template_id]
    to = "+910000000101" if template_id == "staff_alert" else CALLER
    d = run(template_id, consent, variables, to=to)
    assert d.ok and d.reason is None and "{" not in d.text
    assert len(d.text) <= 160 or template_id == "answer_copy"  # short ones fit one segment


def test_status_change_text_is_rendered():
    d = run("status_change", "transactional", {"ticket_id": "HS-1044", "status": "resolved"})
    assert d.text == "College Helpline: request HS-1044 is now resolved."


def test_answer_copy_accepts_both_consent_values():
    _, variables = GOOD["answer_copy"]
    assert run("answer_copy", "caller_requested", variables).ok
    assert run("answer_copy", "offer_accepted", variables).ok


def test_department_phone_number_and_extra_vars_pass():
    v = dict(GOOD["answer_copy"][1], summary="Call the Exam Cell on +910000000101 between 10 and 5.", unused="ignored")
    assert run("answer_copy", "offer_accepted", v).ok


def test_fee_deadline_without_amount_passes():
    v = dict(GOOD["answer_copy"][1], summary="Last date for fee payment is 30 Nov.")
    assert run("answer_copy", "offer_accepted", v).ok


def test_staff_alert_to_emergency_number_passes():
    assert run("staff_alert", "staff", GOOD["staff_alert"][1], to="+910000000902").ok


# ------------------------------------------------------------------ one test per suppression reason
def test_unknown_template():
    cfg = policy.SmsConfig(templates={}, allowed_url_prefixes=CFG.allowed_url_prefixes)
    assert run("status_change", "transactional", GOOD["status_change"][1], cfg=cfg).reason == "unknown_template"


@pytest.mark.parametrize("template_id,bad", [
    ("ticket_created", "caller_requested"), ("ticket_created", "staff"),
    ("status_change", "offer_accepted"), ("status_change", "staff"),
    ("answer_copy", "transactional"), ("answer_copy", "staff"),
    ("staff_alert", "transactional"), ("staff_alert", "caller_requested"), ("staff_alert", "offer_accepted"),
])
def test_wrong_consent(template_id, bad):
    _, variables = GOOD[template_id]
    to = "+910000000101" if template_id == "staff_alert" else CALLER
    assert run(template_id, bad, variables, to=to).reason == "consent_not_allowed"


@pytest.mark.parametrize("bad", ["9000000004", "+0123456789", "+91 9000000004", "+9190", "+9190000000041234567", "abc", ""])
def test_bad_e164(bad):
    assert run("status_change", "transactional", GOOD["status_change"][1], to=bad).reason == "invalid_e164"


def test_staff_alert_number_not_in_sms_alert_numbers():
    d = run("staff_alert", "staff", GOOD["staff_alert"][1], to=CALLER)
    assert d.reason == "staff_number_not_allowed"
    # a transfer number is not an alert number either
    assert run("staff_alert", "staff", GOOD["staff_alert"][1], to="+910000000100").reason == "staff_number_not_allowed"


def test_staff_alert_number_in_sms_alert_numbers():
    for number in ("+910000000101", "+910000000201", "+910000000301", "+910000000001", "+910000000901"):
        assert run("staff_alert", "staff", GOOD["staff_alert"][1], to=number).ok, number


def test_consent_is_checked_before_number():
    assert run("staff_alert", "transactional", GOOD["staff_alert"][1], to="bad").reason == "consent_not_allowed"


def test_missing_var():
    assert run("status_change", "transactional", {"ticket_id": "HS-1044"}).reason == "missing_vars"
    assert run("ticket_created", "transactional", {}).reason == "missing_vars"


def test_vars_too_long():
    v = dict(GOOD["answer_copy"][1], summary="x" * 300)
    assert run("answer_copy", "offer_accepted", v).reason == "vars_too_long"


@pytest.mark.parametrize("summary,rule", [
    ("Your marks are 82 in Data Structures.", "marks_or_grade"),
    ("You scored 45 marks", "marks_or_grade"),
    ("CGPA 8.2", "marks_or_grade"),
    ("Grade B+ in maths", "marks_or_grade"),
    ("Result: 71%", "marks_or_grade"),
    ("Pending dues Rs 4500", "personal_dues"),
    ("Fee of ₹12,000 is overdue", "personal_dues"),
    ("Your fee of Rs 5000 is payable", "money_with_person"),
    ("Student Rahul must pay 5000 rupees", "money_with_person"),
    ("Outstanding fees 45000", "personal_dues"),
    ("Balance: 2300", "personal_dues"),
    ("INR4500 pending", "personal_dues"),
    ("owes 5000", "personal_dues"),
    ("balance 12 345", "personal_dues"),
    ("scored 82 in maths", "marks_or_grade"),
    ("secured 82", "marks_or_grade"),
    ("got 82/100", "marks_or_grade"),
    ("result: pass", "marks_or_grade"),
    ("enrolment 2021CS1234 and name Rahul", "roll_number_with_name"),
    ("बकाया ४५००० pending", "personal_dues"),
    ("Rahul Sharma 2400271549999", "roll_number_with_name"),
    ("Roll no 21CS1234 Priya Singh", "roll_number_with_name"),
    ("Mr Kumar roll number: 24002715", "roll_number_with_name"),
])
def test_pii_in_vars(summary, rule):
    v = dict(GOOD["answer_copy"][1], summary=summary)
    d = run("answer_copy", "offer_accepted", v)
    assert d.reason == "pii_in_vars", summary
    assert policy.pii_in_vars(v) == rule


def test_pii_across_two_vars_roll_in_one_name_in_another():
    v = {"ticket_id": "EX-1001", "summary": "Roll 2400271549999 and Priya Singh need help"}
    assert run("staff_alert", "staff", v, to="+910000000101").reason == "pii_in_vars"
    v2 = {"ticket_id": "EX-1001", "summary": "Needs help", "extra": "Priya Singh 2400271549999"}  # extra var scanned too
    assert run("staff_alert", "staff", v2, to="+910000000101").reason == "pii_in_vars"


def test_roll_number_alone_or_name_alone_passes():
    assert policy.pii_in_vars({"summary": "Roll 21CS1234 needs help"}) is None
    assert policy.pii_in_vars({"summary": "Priya Singh needs help"}) is None


@pytest.mark.parametrize("url", [
    "https://evil.example/login", "http://college.example/x", "https://college.example.evil.com/a",
    "www.college.example/a", "bit.ly/abc",
])
def test_url_outside_allowed_prefixes(url):
    v = dict(GOOD["answer_copy"][1], url=url)
    assert run("answer_copy", "offer_accepted", v).reason == "url_not_allowed", url


def test_url_inside_vars_summary_also_checked():
    v = dict(GOOD["answer_copy"][1], summary="See https://phish.example/now for details")
    assert run("answer_copy", "offer_accepted", v).reason == "url_not_allowed"


def test_allowed_url_with_trailing_punctuation():
    v = dict(GOOD["answer_copy"][1], summary="Details at https://college.example/fees.")
    assert run("answer_copy", "offer_accepted", v).ok


def test_check_order_first_failure_wins():
    # wrong consent AND bad number AND missing var AND pii: consent is reported
    assert run("status_change", "staff", {"status": "marks 80"}, to="bad").reason == "consent_not_allowed"
    # bad number AND missing var: number is reported
    assert run("status_change", "transactional", {}, to="bad").reason == "invalid_e164"
    # missing var AND pii: missing var is reported
    assert run("answer_copy", "offer_accepted", {"summary": "marks 80"}).reason == "missing_vars"
    # pii AND bad url: pii is reported
    v = dict(GOOD["answer_copy"][1], summary="marks 80", url="https://evil.example/")
    assert run("answer_copy", "offer_accepted", v).reason == "pii_in_vars"


def test_render_is_plain_substitution():
    assert policy.render("a {x} b", {"x": "{y}"}) == "a {y} b"
    assert policy.render("{x}{x}", {"x": "1"}) == "11"


@pytest.mark.parametrize("summary", [
    "Hostel fee for 2025 session", "Fee structure 2025 26 posted", "Mess fee 3500 per month for all students",
    "Bus fare 20 rupees per trip", "Office open 10% earlier", "Pay 5000 rupees at the accounts counter",
    "Total 45,000 for the semester", "Exam starts at 10:30 on 12 Dec", "Library fine is charged per day",
])
def test_generic_college_information_passes(summary):
    v = dict(GOOD["answer_copy"][1], summary=summary)
    assert run("answer_copy", "offer_accepted", v).ok, summary


@pytest.mark.parametrize("url", [
    "evil.site/pay", "evil.online", "evil.tk/pay", "goo.gl/x", "1.2.3.4/pay", "college.example/fees",
    "wa.me/pay", "https://college.example/../admin", "https://college.example/∕evil.com",
    "pay at example.org",
])
def test_url_whitelist_has_no_tld_list_to_dodge(url):
    v = dict(GOOD["answer_copy"][1], summary=f"See {url} now")
    assert run("answer_copy", "offer_accepted", v).reason == "url_not_allowed", url
