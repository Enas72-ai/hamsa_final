from flask import Flask, jsonify, request
from flask_cors import CORS
import json
import os
import re
import base64
from dotenv import load_dotenv
from pydantic import BaseModel

load_dotenv()

app = Flask(__name__)
CORS(app)

KB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'kb_hamsa.json')

GEMINI_API_KEY = os.getenv('GEMINI_API_KEY', '')
GEMINI_MODEL = os.getenv('GEMINI_MODEL', 'gemini-2.5-flash')

try:
    from google import genai
    from google.genai import types as genai_types
    _client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None
except ImportError:
    genai = None
    genai_types = None
    _client = None


class StoryOutput(BaseModel):
    story: str
    scene_description: str


# ------------------------------------------------------------------ #
# Existing route — unchanged
# ------------------------------------------------------------------ #
@app.route('/get-data', methods=['GET'])
def get_data():
    try:
        with open('kb_hamsa.json', 'r', encoding='utf-8') as f:
            data = json.load(f)
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ------------------------------------------------------------------ #
# Knowledge Base helpers (used only by /api/generate-story)
# ------------------------------------------------------------------ #
def load_kb():
    with open(KB_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)


def tokenize(text):
    if not text:
        return set()
    text = re.sub(r'[^\w\s]', ' ', text, flags=re.UNICODE)
    return {t for t in text.split() if len(t) > 1}


def match_scenario(kb, context_text, noise_level=None):
    scenarios = kb.get('behavioral_scenarios', [])
    if not scenarios:
        return None

    query_tokens = tokenize(context_text)
    high_hints = ['مرتفع', 'ضجيج', 'ازدحام', 'صاخب', 'high', 'loud', 'noisy']
    low_hints = ['هادئ', 'منخفض', 'quiet', 'low']

    best, best_score = None, -1
    for sc in scenarios:
        candidate = f"{sc.get('title_ar', '')} {sc.get('trigger_ar', '')}"
        candidate_tokens = tokenize(candidate)
        score = len(query_tokens & candidate_tokens)

        if noise_level:
            nl = noise_level.lower()
            if any(h in nl for h in high_hints) and sc.get('anxiety_level') == 'high':
                score += 2
            if any(h in nl for h in low_hints) and sc.get('anxiety_level') == 'low':
                score += 1

        if score > best_score:
            best_score = score
            best = sc

    if best is None or best_score <= 0:
        best = scenarios[0]
    return best


def get_template_for_scenario(kb, scenario_id):
    for t in kb.get('social_stories_templates', []):
        if t.get('linked_scenario_id') == scenario_id:
            return t
    return None


def get_source_by_id(kb, source_id):
    for s in kb.get('authentic_sources', []):
        if s.get('id') == source_id:
            return s
    return None


def get_generation_sources(kb):
    policy = kb.get('educational_policy', {})
    source_ids = policy.get('source_ids', [])
    sources = []
    for sid in source_ids:
        src = get_source_by_id(kb, sid)
        if src:
            sources.append({
                'source_id': src.get('id', ''),
                'title': src.get('title', ''),
                'url': src.get('original_url', ''),
            })
    return sources


def validate_story(kb, story):
    policy = kb.get('educational_policy', {})
    constraints = policy.get('content_generation_constraints', {})
    max_words = constraints.get('max_sentence_length_words', 12)

    sentences = [s.strip() for s in re.split(r'[.!?\n]', story) if s.strip()]
    sentence_count_ok = 3 <= len(sentences) <= 7

    long_sentences = [s for s in sentences if len(s.split()) > max_words + 4]
    sentence_length_ok = len(long_sentences) == 0

    negative_markers = ["don't", 'never', 'stupid', 'bad', 'wrong', 'forbidden', 'must not']
    has_negative = any(m in story.lower() for m in negative_markers)

    coping_mentioned = any(
        kw in story.lower() for kw in ['tool', 'headphone', 'breathe', 'count', 'calm', 'ball']
    )

    return [
        {'label': 'Sentence count within target range (3-7 sentences)', 'pass': sentence_count_ok},
        {'label': 'Sentences are simple and not overly long', 'pass': sentence_length_ok},
        {'label': 'Free of negative words or harsh commands', 'pass': not has_negative},
        {'label': 'Includes a coping or calming strategy', 'pass': coping_mentioned},
    ]


# ------------------------------------------------------------------ #
# AI generation (Gemini, English output)
# ------------------------------------------------------------------ #
def build_system_prompt(scenario, template, policy):
    constraints = policy.get('content_generation_constraints', {})
    max_words = constraints.get('max_sentence_length_words', 12)
    principles = policy.get('core_principles', [])
    principles_text = '\n'.join(
        f"- {p.get('principle_ar')}: {p.get('description_ar')}" for p in principles
    )

    template_steps_text = ''
    if template:
        lines = []
        for step in template.get('structure', []):
            purpose = step.get('purpose_ar', '')
            lines.append(f"  Step {step.get('step')}: {step.get('type')}" + (f" — {purpose}" if purpose else ''))
        template_steps_text = '\n'.join(lines)

    return f"""You are an assistant specialized in writing short "Social Stories" to help prepare autistic \
children emotionally before transitioning from one activity to another, following the TEACCH approach and \
Carol Gray's Social Story standards.

Underlying pedagogical principles guiding this story (background context only):
{principles_text}

Mandatory writing constraints:
- Each sentence should be no more than about {max_words} words.
- Vocabulary: simple and direct, avoid metaphors.
- Tone: calm, positive, never commanding.
- Never include: threats, comparisons to other children, negative references to a diagnosis, or visually \
scary characters or symbols.

Required story structure (follow in order, one sentence per step):
{template_steps_text if template_steps_text else '- Describe the situation, then a feeling or reason, then a coping strategy or guidance, then an encouraging closing sentence.'}

Matched transition scenario from the knowledge base: {scenario.get('title_ar', '')}
(Typical anxiety trigger for this scenario: {scenario.get('trigger_ar', '')})

Output instructions (very important):
- Respond using the required JSON output fields only: "story" and "scene_description".
- "story": the full story as one connected paragraph, written ENTIRELY IN ENGLISH.
- "scene_description": a short English description of what appears in the photo if one was provided, or an \
empty string if not.
- The story MUST be written in English, regardless of the language of any context above.
- Do not mention any source names, references, or links inside the story or the scene description — sources \
are handled separately by the system.
- Do not invent medical or diagnostic information about the child.
"""


def build_user_message(payload):
    learner = payload.get('learner_profile', {}) or {}
    scenario_input = payload.get('scenario', {}) or {}
    preferences = payload.get('preferences', {}) or {}

    name = learner.get('name', 'the child')
    age = learner.get('age')
    known_tools = learner.get('known_tools') or []

    destination_name = scenario_input.get('destination_name') or 'the new place'
    destination_description = scenario_input.get('destination_description') or ''
    noise_level = scenario_input.get('noise_level') or ''

    time_remaining = preferences.get('time_remaining_minutes')
    current_activity = payload.get('current_activity') or ''

    lines = [
        f"Child's name: {name}",
        f"Age: {age} years old" if age else '',
        f"Known calming tools: {', '.join(known_tools)}" if known_tools else '',
        f"Upcoming destination: {destination_name}",
        f"Additional description of the destination: {destination_description}" if destination_description else '',
        f"Expected noise level at the destination: {noise_level}" if noise_level else '',
        f"Time remaining before the transition: {time_remaining} minutes" if time_remaining else '',
        f"Extra note from the parent/teacher: {current_activity}" if current_activity else '',
    ]
    text = '\n'.join(l for l in lines if l)

    if scenario_input.get('mode') == 'camera':
        text += (
            "\n\nNote: An actual photo of the destination is attached — analyze the photo first "
            "(the place, lighting, apparent crowd level) and use that both in scene_description and "
            "when writing the story."
        )
    return text


def call_ai(payload, scenario, template, policy, image_base64=None):
    if _client is None:
        raise RuntimeError(
            'AI provider is not configured. Set GEMINI_API_KEY in your .env file and make sure the '
            '"google-genai" package is installed (pip install google-genai).'
        )

    system_prompt = build_system_prompt(scenario, template, policy)
    user_text = build_user_message(payload)

    contents = [user_text]
    if image_base64:
        image_bytes = base64.b64decode(image_base64)
        contents.append(genai_types.Part.from_bytes(data=image_bytes, mime_type='image/jpeg'))

    response = _client.models.generate_content(
        model=GEMINI_MODEL,
        contents=contents,
        config=genai_types.GenerateContentConfig(
            system_instruction=system_prompt,
            response_mime_type='application/json',
            response_schema=StoryOutput,
        ),
    )

    raw_text = (response.text or '').strip()
    if not raw_text:
        raise RuntimeError('Empty response from the AI provider.')

    parsed = json.loads(raw_text)
    story = (parsed.get('story') or '').strip()
    scene_description = (parsed.get('scene_description') or '').strip()

    if not story:
        raise RuntimeError('The AI response did not include a valid story.')

    return {'story': story, 'scene_description': scene_description}


# ------------------------------------------------------------------ #
# New route: story generation
# ------------------------------------------------------------------ #
@app.route('/api/generate-story', methods=['POST'])
def generate_story():
    try:
        payload = request.get_json(force=True, silent=True) or {}
        scenario_input = payload.get('scenario', {}) or {}

        kb = load_kb()

        context_text = ' '.join(filter(None, [
            scenario_input.get('destination_name'),
            scenario_input.get('destination_description'),
            payload.get('current_activity'),
        ]))

        matched_scenario = match_scenario(kb, context_text, noise_level=scenario_input.get('noise_level'))
        scenario_id = matched_scenario.get('scenario_id') if matched_scenario else None

        template = None
        if matched_scenario:
            template = get_template_for_scenario(kb, scenario_id)
            if not template and matched_scenario.get('recommended_story_template_id'):
                tpl_id = matched_scenario['recommended_story_template_id']
                template = next(
                    (t for t in kb.get('social_stories_templates', []) if t.get('template_id') == tpl_id),
                    None,
                )

        sources = get_generation_sources(kb)

        ai_result = call_ai(
            payload=payload,
            scenario=matched_scenario or {},
            template=template,
            policy=kb.get('educational_policy', {}),
            image_base64=scenario_input.get('image_base64'),
        )

        story = ai_result['story']
        scene_description = ai_result.get('scene_description') or None
        validation = validate_story(kb, story)

        return jsonify({
            'success': True,
            'story': story,
            'scenario': scenario_input.get('destination_name') or (matched_scenario.get('title_ar') if matched_scenario else None),
            'scene_description': scene_description,
            'matched_scenario_id': scenario_id,
            'template_id': template.get('template_id') if template else None,
            'validation': validation,
            'sources': sources,
        })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 200


if __name__ == '__main__':
    app.run(debug=True, port=8000)
