"""One cached local-model interpretation followed by the unchanged real-file flow."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
import time
from urllib.error import HTTPError
from urllib.request import Request, build_opener, ProxyHandler

APP = Path(__file__).resolve().parent
ROOT = APP.parents[1]
SHARED = ROOT / 'app/scrapwise_flow'
sys.path.insert(0, str(SHARED))
from edits import apply_intent
from shared_solver import run_patch

MODEL = 'qwen2.5:7b'
ENDPOINT = 'http://127.0.0.1:11434'
SCHEMA = SHARED / 'intent.schema.json'
MODEL_MANIFEST_SHA256 = '845dbda0ea48ed749caafd9e6037047aa19acfcfd82e704d7ca97d631a0b697e'
FIXED_OPTIONS = {'temperature': 0, 'seed': 1729, 'num_predict': 2048, 'num_ctx': 8192}
KEEP_ALIVE = '5m'
DEPENDENCIES = {
    'app/scrapwise_flow/edits.py': 'e088e91cb52beb9b0418b9b9882342c3b068a37ed77b3f268ba8b0b848671e29',
    'app/scrapwise_flow/shared_solver.py': '0e1478c711e38f476cb9655d8d75d883fc080053c383bc9601ab7ddab333b3bc',
    'app/scrapwise_flow/intent.schema.json': '0513ec578232886f5015665eff3c4cae6df9090a52c71ee45930ed8be3f16a38',
    'reports/scrapwise-first-proof/verify_output.py': 'f4ef0fab03027ebdf554ea6f3f174c0ba36992b3144925b7f005bd52bb165fd6',
    'intelligence/research/cutting-output-20261003/ordinary-control/nest_control.py': '3587e1b984bd269903df0c1e79ee3126eba29cfc555a23096882d70f66afbea5',
}


def utc():
    return datetime.now(timezone.utc).isoformat()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def compact_state_summary(job):
    """Shared interpretation context for whole-part edits; retain full jobs downstream."""
    quantities = {}
    rotations = {}
    for part in job['parts']:
        quantity = part['quantity']
        quantities[quantity] = quantities.get(quantity, 0) + 1
        allowed = tuple(part['allowedRotations'])
        rotations[allowed] = rotations.get(allowed, 0) + 1
    return {
        'units': job['units'],
        'parts': {
            'identityCount': len(job['parts']),
            'quantityDistribution': [{'quantity': quantity, 'identityCount': count}
                                     for quantity, count in sorted(quantities.items())],
            'allowedRotationDistribution': [{'allowedRotations': list(allowed), 'identityCount': count}
                                            for allowed, count in sorted(rotations.items())],
            'editScope': 'Whole collection only; use ids=[] for all parts.',
        },
        'stock': [{key: item[key] for key in ['id', 'kind', 'quantity', 'width', 'height']}
                  for item in job['stock']],
        'spacing': job['spacing'], 'margin': job['margin'],
        'mirrorAllowed': job['mirrorAllowed'], 'objectivePriority': job['objectivePriority'],
        'geometry': 'Full original geometry is retained unchanged by the common processor.',
    }


def unsupported_literal_quantity(message):
    """Reject decimal/fraction literals tied directly to whole-part count wording."""
    atom = r'(?:\d+(?:\.\d*)?|\.\d+)'
    literals = re.compile(r'(?<![\w.])(?:' + atom + r'\s*[/⁄]\s*' + atom +
                          r'|\d+\.\d*|\.\d+)(?![\w.])')
    count_after = re.compile(r'^\s*(?:(?:copy|copies|sets?)\b|(?:of\s+)?(?:each|every|all)\s+(?:the\s+)?parts?\b)', re.I)
    count_before = re.compile(r'\b(?:(?:quantity|quantities|count|copy|copies|sets?)\s*(?:(?:of|for)\s+(?:each|every|all)\s+(?:the\s+)?parts?\s*)?(?:(?:to|at)\s+|[=:]\s*)?|(?:each|every|all)\s+(?:the\s+)?parts?\s+(?:to|at)\s+)$', re.I)
    for literal in literals.finditer(message):
        if count_after.search(message[literal.end():]) or count_before.search(message[:literal.start()]):
            return literal.group()
    return None


def prompt_for(current, original, message):
    instructions = '''Interpret the latest English user message as bounded cutting-layout quantity edits.
Return only the supplied JSON structure. You have no file, browsing or execution tools.
Understand ordinary natural paraphrases; do not demand particular command words.
Current state is context, not requested edits. Change only what the latest message explicitly requests.
The supported domain is:
1. Set the final quantity of EVERY original part to one integer from 1 to 100.
2. Multiply EVERY current part quantity by one explicit integer factor from 1 to 100.
3. Restore original part quantities, when the user explicitly requests original restoration and original state exists.
4. Mark explicitly identified known EXISTING sheets unavailable: set their quantity to 0.
5. Restore availability of explicitly identified known EXISTING sheets to their supplied original positive quantity;
   if no original state exists, an already-positive current quantity may be retained. Never invent a stock count.
6. Restore explicitly requested original existing-stock quantities when original state exists.
A final per-part count is a SET, not an increment or multiplier. A multiplier applies to current counts.
Original restoration is different from returning to an explicitly stated final count.
Sheet removal, loss or exclusion from available stock means unavailable, even when available describes that inventory.
Map a stated sheet name to its exact supplied existing-stock ID. Never invent an ID or edit purchase options.
All unmentioned quantities, source geometry, scale, stock dimensions, spacing, margin, rotations and mirror policy remain unchanged.
A statement consistent with a current fixed constraint may be acknowledged by making no edit to that constraint.
Individual-part edits, decimal/fractional/negative or ambiguous quantities, additive arithmetic, purchase-stock changes,
geometric/spacing/margin/rotation/mirror changes, unknown sheets, undo history and unrelated requests are unsupported.
If ANY part of the latest message is ambiguous or unsupported, action=clarify, operations=[], and question is nonempty.
Never partially apply the supported clauses of an unsupported message.
For a clear supported request, action=solve and question="". A layout request retaining current quantities may use operations=[].
Operation rules:
- parts set_quantity/multiply_quantity uses ids=[] and amount equal to the explicit integer.
- parts restore_original_quantities uses ids=[] and amount=null.
- Part identities are summarized by count because individual edits are unsupported. Always use ids=[] for parts; never enumerate part IDs.
- stock set_quantity uses explicit known existing-stock ids and amount=0 or that sheet's supplied original positive quantity.
- stock restore_original_quantities uses explicit known existing-stock ids and amount=null.
- scope=all restoration is allowed only when original state exists and every purchase-option quantity would remain unchanged.
- Every operation has a nonempty source_quote copied VERBATIM from the latest message. No context-as-edit quotes.
Do not compute or propose a layout. The unchanged program will apply the quantities and generate actual files.
Required JSON schema:
'''
    return instructions + SCHEMA.read_text() + '\nCurrent state:\n' + json.dumps(compact_state_summary(current), ensure_ascii=False) + \
        '\nOriginal state:\n' + (json.dumps(compact_state_summary(original), ensure_ascii=False) if original else 'NOT SUPPLIED') + \
        '\nLatest user message:\n' + message


def validate_schema(value, schema, path='$'):
    """Validate the exact existing schema's used types/required fields/enums."""
    types = schema.get('type')
    types = types if isinstance(types, list) else [types]
    matches = {'object': isinstance(value, dict), 'array': isinstance(value, list),
               'string': isinstance(value, str), 'integer': type(value) is int, 'null': value is None}
    if not any(matches.get(kind, False) for kind in types):
        raise ValueError(f'{path}: model response violates the required type.')
    if 'enum' in schema and value not in schema['enum']:
        raise ValueError(f'{path}: model response violates the allowed values.')
    if isinstance(value, dict):
        properties = schema.get('properties', {})
        if any(name not in value for name in schema.get('required', [])):
            raise ValueError(f'{path}: model response omits required fields.')
        if schema.get('additionalProperties') is False and any(name not in properties for name in value):
            raise ValueError(f'{path}: model response contains unexpected fields.')
        for name, item in value.items():
            if name in properties:
                validate_schema(item, properties[name], path + '.' + name)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            validate_schema(item, schema['items'], f'{path}[{index}]')


def validate_domain(intent, current, original, message):
    if intent['action'] == 'clarify':
        if intent['operations'] or not intent['question'].strip():
            raise ValueError('Actual clarification must contain no edits and a nonempty question.')
        return
    if intent['question']:
        raise ValueError('A solve interpretation must not contain a clarification question.')
    stock = {item['id']: item for item in current['stock']}
    original_stock = {item['id']: item for item in original['stock']} if original else {}
    all_part_ids = {item['id'] for item in current['parts']}
    for edit in intent['operations']:
        if edit['scope'] == 'parts':
            if edit['ids'] and set(edit['ids']) != all_part_ids:
                raise ValueError('The actual interpretation attempts an unsupported individual-part edit.')
            if edit['kind'] != 'restore_original_quantities' and not 1 <= edit['amount'] <= 100:
                raise ValueError('The actual all-parts amount is outside the fixed 1..100 domain.')
        elif edit['scope'] == 'stock':
            if not edit['ids'] or edit['kind'] == 'multiply_quantity':
                raise ValueError('The actual stock edit does not identify supported existing-stock statuses.')
            for item_id in edit['ids']:
                item = stock.get(item_id)
                if item is None or item['kind'] != 'existing':
                    raise ValueError('The actual interpretation edits an unknown or purchase stock option.')
                if edit['kind'] == 'set_quantity' and edit['amount'] != 0:
                    quantity = original_stock.get(item_id, item)['quantity']
                    if quantity < 1 or edit['amount'] != quantity:
                        raise ValueError('The actual stock availability count was invented or changed.')
        elif edit['scope'] == 'all':
            if original is None or edit['kind'] != 'restore_original_quantities' or edit['ids']:
                raise ValueError('Unsupported all-scope operation in the actual interpretation.')
            if any(item['kind'] == 'purchase' and original_stock.get(item['id'], {}).get('quantity') != item['quantity'] for item in current['stock']):
                raise ValueError('All-scope restoration would change a purchase option.')
    # Reuse the exact state/quote validator before any solver call. No response repair.
    apply_intent(intent, current, original, message)


def model_provenance():
    manifest_path = Path.home() / '.ollama/models/manifests/registry.ollama.ai/library/qwen2.5/7b'
    if sha(manifest_path) != MODEL_MANIFEST_SHA256:
        raise ValueError('The parent-selected cached local model manifest changed.')
    manifest = json.loads(manifest_path.read_text())
    layer = next(item for item in manifest['layers'] if item['mediaType'].endswith('.model'))
    blob_path = Path.home() / '.ollama/models/blobs' / layer['digest'].replace(':', '-')
    if not blob_path.exists() or blob_path.stat().st_size != layer['size']:
        raise ValueError('The cached local model blob is unavailable or incomplete.')
    return {'model': MODEL, 'manifestPath': str(manifest_path), 'manifestSha256': sha(manifest_path),
            'blobDeclaredDigest': layer['digest'], 'blobBytes': blob_path.stat().st_size,
            'digestSource': 'Existing local manifest; full blob digest was independently verified in feasibility report.',
            'feasibilityReportSha256': sha(ROOT / 'reports/scrapwise-local-inference-feasibility.json')}


def actual_intent(current, original, message, output, prompt_override, timeout):
    started = time.perf_counter()
    record = {'status': 'RUNNING', 'startedAt': utc(), 'backend': 'Existing local Ollama',
              'modelRequests': 0, 'prewarmRequests': 0, 'metadataRequests': 0,
              'endpoint': ENDPOINT, 'options': FIXED_OPTIONS, 'keepAlive': KEEP_ALIVE,
              'cloudCodexConfigurationChanged': False, 'modelToolsAvailable': False}
    try:
        schema = json.loads(SCHEMA.read_text())
        unsupported_number = unsupported_literal_quantity(message)
        if unsupported_number is not None:
            intent = {'action': 'clarify', 'operations': [],
                      'question': 'What whole-number quantity from 1 to 100 should apply to all parts?'}
            save(output / 'intent.json', intent)
            validate_schema(intent, schema)
            validate_domain(intent, current, original, message)
            record.update(status='INTERPRETATION_RETURNED',
                          backend='Deterministic literal quantity domain check',
                          decisionSource='literal-quantity-domain-check',
                          unsupportedLiteralQuantity=unsupported_number)
            return intent
        record['decisionSource'] = 'local-language-model'
        record['provenance'] = model_provenance()
        prompt = prompt_for(current, original, message) if prompt_override is None else prompt_override
        (output / 'model-prompt.txt').write_text(prompt)
        record['promptSha256'] = hashlib.sha256(prompt.encode()).hexdigest()
        body = {'model': MODEL, 'messages': [{'role': 'user', 'content': prompt}],
                'format': schema, 'stream': False, 'options': FIXED_OPTIONS, 'keep_alive': KEEP_ALIVE}
        save(output / 'model-request.json', body)
        opener = build_opener(ProxyHandler({}))
        record['metadataRequests'] = 1
        with opener.open(ENDPOINT + '/api/version', timeout=min(timeout, 10)) as response:
            version_raw = response.read()
        (output / 'runtime-version.json').write_bytes(version_raw)
        record['actualRuntimeVersion'] = json.loads(version_raw).get('version')
        request = Request(ENDPOINT + '/api/chat', data=json.dumps(body).encode(),
                          headers={'Content-Type': 'application/json'}, method='POST')
        record['modelRequests'] = 1
        request_started = time.perf_counter()
        with opener.open(request, timeout=timeout) as response:
            raw = response.read()
            record['httpStatus'] = response.status
        record['apiElapsedSeconds'] = time.perf_counter() - request_started
        (output / 'model-response.json').write_bytes(raw)
        response = json.loads(raw)
        if response.get('error'):
            raise RuntimeError('Actual local API error: ' + str(response['error']))
        record['timingAndTokens'] = {name: response.get(name) for name in
            ['total_duration', 'load_duration', 'prompt_eval_duration', 'eval_duration', 'prompt_eval_count', 'eval_count']}
        record['done'] = response.get('done')
        record['doneReason'] = response.get('done_reason')
        content = response.get('message', {}).get('content')
        if not isinstance(content, str) or not content.strip():
            raise ValueError('Actual local model response content is empty.')
        (output / 'model-content.txt').write_text(content)
        if response.get('done') is not True or response.get('done_reason') == 'length':
            raise ValueError('Actual local response is incomplete or token-truncated.')
        intent = json.loads(content)
        save(output / 'intent.json', intent)
        validate_schema(intent, schema)
        validate_domain(intent, current, original, message)
        record['status'] = 'INTERPRETATION_RETURNED'
        return intent
    except HTTPError as error:
        (output / 'model-api-error-body.txt').write_bytes(error.read())
        record.update(status='ERROR', httpStatus=error.code, error=str(error))
        raise
    except Exception as error:
        record.update(status='ERROR', error=str(error))
        raise
    finally:
        record.update(completedAt=utc(), elapsedSeconds=time.perf_counter() - started)
        save(output / 'model-call.json', record)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--current-job', required=True, type=Path)
    parser.add_argument('--original-job', type=Path)
    parser.add_argument('--message-file', required=True, type=Path)
    parser.add_argument('--prompt-file', type=Path)
    parser.add_argument('--output-dir', required=True, type=Path)
    parser.add_argument('--case-id')
    parser.add_argument('--attempts', type=int, default=18)
    parser.add_argument('--model-timeout', type=int, default=240)
    args = parser.parse_args()
    started = time.perf_counter()
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=False)
    receipt = {'status': 'RUNNING', 'startedAt': utc(), 'mechanism': 'Cached local language-model quantity interpretation',
               'currentJobSha256': sha(args.current_job), 'originalJobSha256': sha(args.original_job) if args.original_job else None,
               'messageSha256': sha(args.message_file), 'bridgeSha256': sha(Path(__file__)),
               'model': MODEL, 'modelPrewarm': False, 'modelOptions': FIXED_OPTIONS,
               'keepAlive': KEEP_ALIVE, 'attemptsPerStockOption': args.attempts,
               'sharedDependencies': DEPENDENCIES, 'humanOrPhysicalBenefit': 'NOT_MEASURED'}
    try:
        for artifact, digest in DEPENDENCIES.items():
            if sha(ROOT / artifact) != digest:
                raise ValueError('A frozen shared dependency changed: ' + artifact)
        current = json.loads(args.current_job.read_text())
        original = json.loads(args.original_job.read_text()) if args.original_job else None
        message = args.message_file.read_text().strip()
        if not message:
            raise ValueError('Actual latest message is empty.')
        prompt_override = args.prompt_file.read_text() if args.prompt_file else None
        actual_intent(current, original, message, output, prompt_override, args.model_timeout)
        interpretation = json.loads((output / 'model-call.json').read_text())
        receipt.update(intentReadyAt=utc(), intentReadySeconds=time.perf_counter() - started,
                       decisionSource=interpretation['decisionSource'],
                       modelRequests=interpretation['modelRequests'])
        result = run_patch(args.current_job, output / 'intent.json', args.message_file,
                           output, args.original_job, args.case_id, args.attempts)
        receipt.update(status=result['status'], question=result.get('question'),
                       artifactFilesCompletedAt=result.get('artifactFilesCompletedAt'),
                       checkedFileCompletedAt=result.get('checkedFileCompletedAt'),
                       postprocessorSeconds=result['elapsedSeconds'], finalJobSha256=result.get('finalJobSha256'),
                       placementsSha256=result.get('placementsSha256'), svgSha256=result.get('svgSha256'),
                       purchasedArea=result.get('purchasedArea'), totalUsedSheetArea=result.get('totalUsedSheetArea'),
                       requiredPieceCopies=result.get('requiredPieceCopies'), actualSVGCopies=result.get('actualSVGCopies'))
        print(json.dumps({'status': result['status'], 'question': result.get('question'),
                          'checkedFileCompletedAt': result.get('checkedFileCompletedAt')}))
        return {'COMPLETE': 0, 'NO_COMPLETE_OUTPUT': 2, 'CLARIFICATION_REQUIRED': 3}[result['status']]
    except Exception as error:
        receipt.update(status='ERROR', error=str(error))
        raise
    finally:
        receipt.update(completedAt=utc(), requestToCheckedFileSeconds=time.perf_counter() - started)
        save(output / 'flow-receipt.json', receipt)


if __name__ == '__main__':
    raise SystemExit(main())
