"""Quick-triage demo scenarios for the Streamlit inbox."""

SAMPLE_SCENARIOS = {
    "💳 Double charge": {
        "sender": "jane.martinez@example.com",
        "subject": "Charged twice on my card",
        "body": (
            "Hi support, my name is Jane Martinez. My account ID is ACC-998877 "
            "and I was charged twice on card 4111-1111-1111-1111. "
            "Please call me at +1-212-555-0100 to resolve this urgently."
        ),
    },
    "🔒 MFA lockout": {
        "sender": "priya.shah@example.com",
        "subject": "Locked out after MFA reset",
        "body": (
            "I'm Priya Shah and I cannot log in after my MFA was reset. "
            "Account ID ACC-44012, SSN 000-00-0000 on file. "
            "Please call +1-212-555-0199."
        ),
    },
    "📶 VPN failure": {
        "sender": "sam.okonkwo@example.com",
        "subject": "VPN drops every 10 minutes",
        "body": (
            "This is Sam Okonkwo (sam.okonkwo@example.com). "
            "Our corporate VPN disconnects every 10 minutes since last night's patch. "
            "Call +1-212-555-0133. Urgent — blocking the entire team."
        ),
    },
    "💬 General thanks": {
        "sender": "jordan.lee@example.com",
        "subject": "Thanks for last week's webinar",
        "body": (
            "Hi, this is Jordan Lee. No action needed — just wanted to say "
            "the webinar last Tuesday was great and was provided without charge. "
            "Really appreciated it!"
        ),
    },
    "🏥 Healthcare billing": {
        "sender": "sarah.johnson@patient.example.com",
        "subject": "Question about my ER visit bill",
        "body": (
            "Hello, I'm Sarah Johnson. I received an unexpected invoice for my "
            "emergency room visit. My SSN on file is 000-00-0003 and my patient "
            "account is ACC-771234. The billed amount doesn't match what my "
            "insurer told me. Please contact me at +1-617-555-0177 to clarify."
        ),
    },
    "💼 HR payroll issue": {
        "sender": "marcus.chen@employee.example.com",
        "subject": "Payroll discrepancy — missing overtime",
        "body": (
            "I'm Marcus Chen (marcus.chen@employee.example.com). My employee "
            "account ACC-33401 was not credited for 12 hours of overtime last "
            "pay period. My SSN on file is 000-00-0004. "
            "Please call me at +1-415-555-0218 urgently."
        ),
    },
    "⚖️ GDPR deletion": {
        "sender": "emma.thornton@example.com",
        "subject": "GDPR right-to-erasure request",
        "body": (
            "I am Emma Thornton. I am exercising my right to erasure under GDPR "
            "Article 17. Please delete all personal data for account ACC-55601. "
            "Confirm to emma.thornton@example.com or call +1-312-555-0244. "
            "You have 30 days to comply."
        ),
    },
}
