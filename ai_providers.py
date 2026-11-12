"""Server-side AI adapters. Supports Elastic Cloud and OpenAI. Provider choice never comes from client messages."""
import json
import os
import re
import urllib.request
import urllib.error
from urllib.parse import urlparse

def provider():
    return os.environ.get('AI_PROVIDER', 'openai').strip().lower()

def ready():
    p = provider()
    if p == 'elastic':
        return all(os.environ.get(k, '').strip() for k in ('ELASTIC_KIBANA_URL', 'ELASTIC_API_KEY', 'ELASTIC_AGENT_ID'))
    if p == 'openai':
        return bool(os.environ.get('OPENAI_API_KEY') and os.environ.get('OPENAI_MODEL'))
    if p == 'demo':
        return True
    return False

def base_url():
    value = os.environ.get('ELASTIC_KIBANA_URL', '').strip().rstrip('/')
    parsed = urlparse(value)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('Enter the HTTPS Kibana URL from your Elastic Cloud project, without credentials or query parameters.')
    if not any(parsed.hostname.endswith(suffix) for suffix in ('.elastic.cloud', '.elastic-cloud.com', '.cloud.es.io', '.found.io')):
        raise ValueError('Use the Kibana endpoint of your Elastic Cloud project.')
    if parsed.path and not re.fullmatch(r'/s/[a-zA-Z0-9_-]+', parsed.path):
        raise ValueError('Use the Kibana base URL, optionally followed by /s/your-space.')
    return value

def agent_id():
    value = os.environ.get('ELASTIC_AGENT_ID', '').strip()
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', value): raise ValueError('Enter a valid Elastic agent ID.')
    return value

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl): return None

def elastic_request(method, path, payload=None, key=None):
    secret = key or os.environ.get('ELASTIC_API_KEY', '').strip()
    if not secret: raise ValueError('An Elastic API key is required.')
    request = urllib.request.Request(base_url() + path, data=json.dumps(payload).encode() if payload is not None else None,
        headers={'Authorization': 'ApiKey ' + secret, 'kbn-xsrf': 'true', 'Content-Type': 'application/json'}, method=method)
    with urllib.request.build_opener(NoRedirect()).open(request, timeout=60) as response:
        return json.load(response)

def offline_generate(messages, records=None):
    user_msg = ""
    for m in reversed(messages):
        if m.get('role') == 'user':
            content = m.get('content', '')
            if not content.startswith('{"records":'):
                user_msg = content
                break
    q = user_msg.lower()
    currency = (records or {}).get('currency', 'USD')
    rules = (records or {}).get('rules', {})
    price = (rules.get('sharePrice', 100) / 100) if rules else 1.0

    if any(k in q for k in ('how do i join', 'how to join', 'join a group', 'invitation')):
        return (
            "To join a SaveKin circle:\n\n"
            "1. Ask the group President for their private invitation link.\n"
            "2. Click 'Join a group' in the navigation menu.\n"
            "3. Review the founding rules: monthly share price, savings goal, cycle length, and surplus policy.\n"
            "4. Choose your initial monthly shares and check the box to accept the rules.\n\n"
            "Note: If contributions have already begun, late joiners either wait for the next cycle or catch up on elapsed months, depending on the circle's accepted rules."
        )
    elif any(k in q for k in ('catch-up', 'catch up', 'arrears', 'owe')):
        return (
            f"Understanding catch-up obligations and arrears:\n\n"
            f"In SaveKin, each share has a fixed price per month (currently {currency} {price:.2f} in this circle).\n"
            "When you increase your shares mid-cycle, you commit to that share level for all months that have already elapsed in the current cycle.\n\n"
            "This protects fairness by ensuring late share increases cannot claim a disproportionate surplus at settlement. Any catch-up amount appears as arrears until paid."
        )
    elif any(k in q for k in ('treasurer contribute', 'paying themselves', 'treasury fund')):
        return (
            "How the Treasurer contributes without self-payments:\n\n"
            "Since the Treasurer manages the group's funds, paying themselves via PayPal would incur unnecessary transaction fees.\n\n"
            "Instead, the Treasurer chooses 'Contribute treasury funds' in their group, declares the amount set aside, and enters an external reference with optional evidence.\n\n"
            "The separate President then independently reviews and confirms this in Decisions before any savings credit is recorded."
        )
    elif any(k in q for k in ('choose a purpose', 'savings goal', 'goal planning', 'choose a goal', 'plan')):
        return (
            "Recommended Savings Plan & Milestones:\n\n"
            "1. Emergency Reserve: 3 to 6 months of living expenses, typically 10–50 units/month per member.\n"
            "2. Shared Project / Asset Purchase: A target goal (e.g. $1,200) split evenly across 12 months with 5 members ($20/month per member).\n"
            "3. Annual Holiday / Milestone: A 12-month repeating cycle distributing principal plus accumulated surplus at year-end.\n\n"
            "Tip: Start with a comfortable monthly share price that all participants can reliably afford to avoid mid-cycle arrears."
        )
    elif any(k in q for k in ('compare', 'one-time', 'repeating', 'cycle')):
        return (
            "Comparing Cycle Types in SaveKin:\n\n"
            "• Date-Ending Cycle: Runs until a specific calendar deadline. Ideal for fixed-date events or holiday funds.\n"
            "• Goal-Ending Cycle: Continues until the circle reaches its target savings amount, then pauses new contributions while allowing arrears to clear.\n"
            "• Repeating Cycle: Automatically prepares for the next cycle after payouts are sent. Scheduled share increases and waitlisted members activate seamlessly.\n\n"
            "Surplus Option: Groups can choose to carry surplus forward into the next cycle as a community buffer or distribute it proportionally by paid shares."
        )
    elif any(k in q for k in ('shares', 'fine', 'voting', 'rules', 'governance')):
        return (
            "SaveKin Governance & Community Rules:\n\n"
            "• Democratic 2/3 Majority: Proposing new rules or appointing officers requires approval from at least two-thirds of active members.\n"
            "• Distinct Officers: The President and Treasurer must be two different individuals. Both must independently sign off on settlement and early exits.\n"
            "• Early Exits: Members can request an early exit. If approved, their principal is returned minus the accepted penalty, without cycle surplus.\n"
            "• Member Consent: Nominated officers must also vote yes to consent to their election."
        )
    else:
        return (
            "SaveKin Helper (Savings & Community Guide):\n\n"
            "I'm here to help your circle budget, understand rules, and plan savings:\n"
            "• Need help picking a goal? Ask for budgeting suggestions or roadmap advice.\n"
            "• Unsure about rules? Ask about 2/3 voting, officer separation, or surplus distribution.\n"
            "• Questions on payments? Ask about catch-up shares, fees, or PayPal sandbox payouts.\n\n"
            "What would you like to explore for your circle?"
        )

def generate(instructions, messages, records=None):
    p = provider()
    if p == 'elastic':
        result = elastic_request('POST', '/api/agent_builder/converse', {
            'agent_id': agent_id(),
            'input': json.dumps({'conversation': [{'role': m['role'], 'content': m['content'][:4000]} for m in messages]}),
            'configuration_overrides': {'instructions': instructions,
                'enable_elastic_capabilities': False, 'tools': [], 'skill_ids': []}})
        answer = result.get('response', {}).get('message', '')
        if not isinstance(answer, str): raise ValueError('Elastic returned no text reply.')
        return answer
    elif p == 'openai':
        if not os.environ.get('OPENAI_API_KEY') or not os.environ.get('OPENAI_MODEL'):
            raise ValueError('OpenAI configuration is missing.')
        payload = {'model': os.environ['OPENAI_MODEL'], 'store': False, 'max_output_tokens': 1400,
            'instructions': instructions, 'input': messages}
        request = urllib.request.Request('https://api.openai.com/v1/responses', data=json.dumps(payload).encode(),
            headers={'Authorization': 'Bearer ' + os.environ['OPENAI_API_KEY'], 'Content-Type': 'application/json'})
        with urllib.request.urlopen(request, timeout=40) as response: result = json.load(response)
        return '\n'.join(part['text'] for item in result.get('output', []) if item.get('type') == 'message'
            for part in item.get('content', []) if part.get('type') == 'output_text')
    elif p == 'demo':
        return offline_generate(messages, records)
    else:
        raise ValueError('Choose AI_PROVIDER=openai, elastic, or demo.')
