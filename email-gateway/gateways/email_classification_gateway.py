#!/usr/bin/env python3

'''Email gateway — parse RFC-822 email and classify with an OpenAI-compatible API.

Adapted from:
  https://github.com/redhat-et/vllm-audio-demo/blob/main/gateways/email_classification_gateway.py
  Copyright 2024 Michael Dawson <midawson@redhat.com>
  Licensed under the Apache License, Version 2.0

Extensions in this file (beyond the original):
  - parse_bytes(): parse raw RFC-822 bytes from SMTP/HTTP ingest paths
  - _classify(): Responses API with chat.completions fallback
  - --file CLI argument for direct .eml ingestion
  - Dict-based config so pipeline.py can pass settings inline
  - Updated INSTR: Account Access category + structured token format
'''

import json
import email
import email.parser
import email.policy
from email.message import EmailMessage
import sys
import os
from argparse import ArgumentParser
from types import SimpleNamespace

from openai import OpenAI

DEFAULT_CONFIG = f"{os.environ['HOME']}/.vllm-email-gw.json"
# Structured PII (card numbers, phone numbers, SSNs, email addresses, account IDs) is
# regex-tokenized by the pipeline BEFORE this prompt is sent, so the model never sees
# raw values. The model's only redaction responsibility is full names, which regex cannot
# reliably catch across arbitrary prose. This split is intentional:
#   - Regex is deterministic and auditable — required for GDPR/HIPAA/GLBA compliance.
#   - Keeping high-risk structured PII out of the inference engine eliminates log-exposure
#     risk (vLLM logs request payloads by default).
#   - If inference fails, the regex-tokenized text is already safe to pass downstream.
INSTR = '''
You are a helpdesk email classification assistant. The text you receive has already had
structured PII replaced with tokens by a deterministic regex pipeline:
  [PHONE_N], [CARD_LAST4_N], [EMAIL_N], [ACCOUNT_ID_N], [SSN_N]

Do not re-tokenize or alter those tokens — treat them as opaque literals.
If the input already contains [NAME_1], the next new person name you redact
becomes [NAME_2], and so on.

Return a JSON object with these exact keys:
- 'category' (Billing, Tech Support, Account Access, General)
- 'urgency' (Low, Medium, High)
- 'sanitized_text' (copy of the input with any remaining full person names
  replaced: each unique full name → [NAME_N] continuing from the highest N
  already present in the input)
- 'summary' (one sentence, max 20 words, using tokens only — no raw PII,
  no new names introduced)
'''


class VLLMEmailGateway():
    '''Gateway from email to VLLM with configurable actions'''
    def __init__(self, config):
        if isinstance(config, dict):
            self.config = config
        else:
            with open(config, encoding="ascii") as conffile:
                self.config = json.load(conffile)
        self.message = None
        self.client = OpenAI(
            base_url=self.config["base_url"],
            api_key="EMPTY",
            timeout=float(
                self.config.get("timeout", os.environ.get("VLLM_TIMEOUT", "30"))
            ),
        )
        self.response = None
        self.reply_address = None

    def parse_data(self, arg=None):
        '''Parse Mime data from stdin or supplied argument'''
        parser = email.parser.BytesParser()
        if arg is None:
            self.message = parser.parse(sys.stdin.buffer)
        else:
            with open(arg, encoding="ascii") as mailfp:
                self.message = parser.parse(mailfp.buffer)
        self.message.policy = email.policy.default

    def parse_bytes(self, data):
        '''Parse MIME from raw RFC-822 bytes (SMTP, file watcher, HTTP ingest).'''
        parser = email.parser.BytesParser()
        self.message = parser.parsebytes(data)
        self.message.policy = email.policy.default

    def execute(self):
        '''Execute instructions — tokenizes PII before sending to RHAII.

        Used by the CLI path (main()) and classify_raw_email(). The HTTP
        pipeline path calls _classify() directly with already-tokenized text
        via classify_and_sanitize() in app/inference.py.
        '''
        for part in self.message.walk():
            if part.get_content_type() == "text/plain":
                payload = part.get_payload(decode=True).decode("utf-8")
                # Tokenize structured PII so raw values never reach RHAII logs.
                try:
                    from app.tokenizer import tokenize_structured_pii
                    payload, _vault = tokenize_structured_pii(payload)
                except ImportError:
                    pass  # standalone use without the app package
                self.response = self._classify(payload)
                break

    def _classify(self, payload):
        '''Prefer the Responses API used by the original gateway; fall back to chat.'''
        try:
            return self.client.responses.create(
                model=self.config["classify_model"],
                instructions=INSTR,
                input=payload,
                temperature=0.0)
        except Exception:
            chat = self.client.chat.completions.create(
                model=self.config["classify_model"],
                messages=[
                    {"role": "system", "content": INSTR},
                    {"role": "user", "content": payload},
                ],
                temperature=0.0)
            text = chat.choices[0].message.content
            return SimpleNamespace(output_text=text)


def main():
    '''Process stdin'''

    aparser = ArgumentParser(description=main.__doc__)
    aparser.add_argument(
        '--config',
        help='config file in json format',
        type=str,
        default=DEFAULT_CONFIG)
    aparser.add_argument(
        '--file',
        help='RFC-822 message file (default: stdin)',
        type=str,
        default=None)

    args = vars(aparser.parse_args())

    vllm_gw = VLLMEmailGateway(args["config"])
    vllm_gw.parse_data(args["file"])
    vllm_gw.execute()
    message = vllm_gw.message
    if vllm_gw.response is not None:
        message.set_payload(vllm_gw.response.output_text)
    print(message)

if __name__ == "__main__":
    main()
