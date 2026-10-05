"""Run the unchanged first-proof ordinary packing engine on a supplied job.

This adapter changes input/output routing only. Both comparison arms can call it.
"""
import argparse
import hashlib
import importlib.util
import io
import json
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
import shutil
import tempfile
import time

from edits import apply_intent

ROOT = Path(__file__).resolve().parents[2]
ENGINE = ROOT / 'intelligence/research/cutting-output-20261003/ordinary-control/nest_control.py'
ENGINE_SHA256 = '3587e1b984bd269903df0c1e79ee3126eba29cfc555a23096882d70f66afbea5'
VERIFIER = ROOT / 'reports/scrapwise-first-proof/verify_output.py'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def utc():
    return datetime.now(timezone.utc).isoformat()


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def solve(job_path, output_dir, attempts=18):
    job_path = Path(job_path).resolve()
    output_dir = Path(output_dir).resolve()
    engine_hash = sha(ENGINE)
    if engine_hash != ENGINE_SHA256:
        raise ValueError('The frozen shared engine changed.')
    spec = importlib.util.spec_from_file_location('scrapwise_exact_shared_engine', ENGINE)
    engine = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(engine)
    job = json.loads(job_path.read_text())
    # The engine reads ROOT / artifact; an absolute supplied path keeps the job exact.
    # The engine's HERE is used only for output routing after its imports completed.
    with tempfile.TemporaryDirectory(prefix='scrapwise-shared-solver-') as work:
        engine.HERE = Path(work)
        log = io.StringIO()
        with redirect_stdout(log):
            details = engine.solve({'artifact': str(job_path), 'sha256': sha(job_path)}, attempts)
        produced = engine.HERE / 'polygon-control' / job['caseId']
        output_dir.mkdir(parents=True, exist_ok=True)
        for source in produced.iterdir():
            destination = output_dir / source.name
            if destination.exists():
                raise FileExistsError(destination)
            shutil.copy2(source, destination)
        (output_dir / 'solve-events.jsonl').write_text(log.getvalue())
    receipt = {
        'engine': str(ENGINE.relative_to(ROOT)),
        'engineSha256': engine_hash,
        'adapterSha256': sha(Path(__file__)),
        'attemptsPerStockOption': attempts,
        'inputSha256': sha(job_path),
        'engineDetailsUnmodified': True,
        'originalContractFieldMeaning': 'The engine retains the first-proof contract digest as provenance; it is not the new flow-proof contract.',
    }
    (output_dir / 'shared-engine-receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    return details


def verify(job_path, output_dir):
    spec = importlib.util.spec_from_file_location('scrapwise_root_file_verifier', VERIFIER)
    checker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checker)
    report = checker.verify(job_path, output_dir)
    save(output_dir / 'independent-file-check.json', report)
    if not report['valid']:
        raise ValueError('The actual exported layout failed the root file checker.')
    return report


def run_patch(current_job_path, patch_path, message_file, output_dir, original_job_path=None,
              case_id=None, attempts=18):
    started = time.perf_counter()
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    job_path = output_dir / 'job.json'
    if job_path.exists():
        raise FileExistsError(job_path)
    receipt = {'status': 'RUNNING', 'startedAt': utc(), 'currentJobSha256': sha(current_job_path),
               'patchSha256': sha(patch_path), 'messageSha256': sha(message_file),
               'originalJobSha256': sha(original_job_path) if original_job_path else None,
               'sharedEngineSha256': sha(ENGINE), 'verifierSha256': sha(VERIFIER),
               'postprocessorSha256': sha(Path(__file__)), 'attemptsPerStockOption': attempts}
    try:
        current = json.loads(Path(current_job_path).read_text())
        original = json.loads(Path(original_job_path).read_text()) if original_job_path else None
        message = Path(message_file).read_text().strip()
        intent = json.loads(Path(patch_path).read_text())
        save(output_dir / 'starting-job.json', current)
        (output_dir / 'utterance.txt').write_text(message + '\n')
        proposed = apply_intent(intent, current, original, message)
        if proposed is None:
            receipt.update(status='CLARIFICATION_REQUIRED', question=intent['question'])
            return receipt
        if case_id:
            proposed['caseId'] = case_id
        proposed['utterance'] = message
        save(job_path, proposed)
        details = solve(job_path, output_dir, attempts)
        receipt['solverStatus'] = details['status']
        if details['status'] != 'COMPLETE':
            receipt['status'] = 'NO_COMPLETE_OUTPUT'
            return receipt
        receipt['artifactFilesCompletedAt'] = utc()
        check = verify(job_path, output_dir)
        receipt.update(status='COMPLETE', checkedFileCompletedAt=utc(), finalJobSha256=sha(job_path),
                       placementsSha256=check['placementsSha256'], svgSha256=check['svgSha256'],
                       purchasedArea=check['purchasedArea'], totalUsedSheetArea=check['totalUsedSheetArea'],
                       requiredPieceCopies=check['requiredPieceCopies'], actualSVGCopies=check['actualSVGCopies'])
        return receipt
    except Exception as error:
        receipt.update(status='ERROR', error=str(error))
        raise
    finally:
        receipt.update(completedAt=utc(), elapsedSeconds=time.perf_counter() - started)
        save(output_dir / 'postprocessor-receipt.json', receipt)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--current-job', required=True, type=Path)
    parser.add_argument('--original-job', type=Path)
    parser.add_argument('--patch-json', required=True, type=Path)
    parser.add_argument('--message-file', required=True, type=Path)
    parser.add_argument('--output-dir', required=True, type=Path)
    parser.add_argument('--case-id')
    parser.add_argument('--attempts', type=int, default=18)
    args = parser.parse_args()
    receipt = run_patch(args.current_job, args.patch_json, args.message_file, args.output_dir,
                        args.original_job, args.case_id, args.attempts)
    print(json.dumps({'status': receipt['status'], 'checkedFileCompletedAt': receipt.get('checkedFileCompletedAt')}))
    return {'COMPLETE': 0, 'NO_COMPLETE_OUTPUT': 2, 'CLARIFICATION_REQUIRED': 3}[receipt['status']]


if __name__ == '__main__':
    raise SystemExit(main())
