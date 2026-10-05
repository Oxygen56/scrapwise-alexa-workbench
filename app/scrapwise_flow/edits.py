"""Shared quantity-only state editing, with no utterance matcher or packing logic."""
import copy


def state_summary(job):
    return {
        'caseId': job['caseId'], 'units': job['units'],
        'parts': [{'id': p['id'], 'quantity': p['quantity']} for p in job['parts']],
        'stock': job['stock'], 'spacing': job['spacing'], 'margin': job['margin'],
        'mirrorAllowed': job['mirrorAllowed'], 'objectivePriority': job['objectivePriority'],
        'geometry': 'Original part vertices, scale and allowed rotations are immutable and are retained by the program.',
    }



def apply_intent(intent, current, original, message):
    if set(intent) != {'action', 'operations', 'question'}:
        raise ValueError('Unexpected interpretation fields.')
    if intent['action'] == 'clarify':
        if intent['operations'] or not intent['question'].strip():
            raise ValueError('A clarification must ask a question and leave quantities unchanged.')
        return None
    if intent['action'] != 'solve' or intent['question']:
        raise ValueError('Unsupported interpretation action.')
    proposed = copy.deepcopy(current)
    collections = {scope: {item['id']: item for item in proposed[scope]} for scope in ['parts', 'stock']}
    original_collections = None
    if original is not None:
        original_collections = {scope: {item['id']: item for item in original[scope]} for scope in ['parts', 'stock']}
        for scope in ['parts', 'stock']:
            if collections[scope].keys() != original_collections[scope].keys():
                raise ValueError('The supplied original state has different item IDs.')
    for operation in intent['operations']:
        if set(operation) != {'kind', 'scope', 'ids', 'amount', 'source_quote'}:
            raise ValueError('Unexpected edit fields.')
        kind, scope, ids, amount, quote = [operation[k] for k in ['kind', 'scope', 'ids', 'amount', 'source_quote']]
        if not isinstance(quote, str) or not quote or quote not in message:
            raise ValueError('An edit lacks a literal quote from the latest message.')
        if scope not in {'parts', 'stock', 'all'} or not isinstance(ids, list) or len(ids) != len(set(ids)):
            raise ValueError('Invalid edit scope or duplicate IDs.')
        if scope == 'all' and (kind != 'restore_original_quantities' or ids):
            raise ValueError('All-scope edits are limited to original-quantity restoration.')
        scopes = ['parts', 'stock'] if scope == 'all' else [scope]
        for target_scope in scopes:
            items = collections[target_scope]
            targets = ids or list(items)
            if any(item_id not in items for item_id in targets):
                raise ValueError('Unknown item in the requested edit.')
            if kind == 'restore_original_quantities':
                if original_collections is None or amount is not None:
                    raise ValueError('Original quantities were not supplied or restoration has an amount.')
                for item_id in targets:
                    items[item_id]['quantity'] = original_collections[target_scope][item_id]['quantity']
            elif kind in {'set_quantity', 'multiply_quantity'}:
                if type(amount) is not int or amount < 0:
                    raise ValueError('Quantity or multiplier must be a nonnegative integer.')
                for item_id in targets:
                    items[item_id]['quantity'] = amount if kind == 'set_quantity' else items[item_id]['quantity'] * amount
            else:
                raise ValueError('Unsupported quantity operation.')
    # This is a quantity-only operation. Assert that the engine will receive all
    # original geometry, source identity, rotations, stock size and constraints.
    def without_quantities(job):
        stripped = copy.deepcopy(job)
        for scope in ['parts', 'stock']:
            for item in stripped[scope]:
                item.pop('quantity')
        return stripped
    if without_quantities(proposed) != without_quantities(current):
        raise ValueError('The edit changed something other than quantities.')
    return proposed


