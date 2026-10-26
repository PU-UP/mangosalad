"""Read-only model context projection; canonical API/history remain unchanged."""
import copy
import json
from pathlib import Path


def reviews(data):
    path = Path(data)/'invest-context-reviews.json'
    return json.loads(path.read_text()) if path.exists() else []


def report_reference(report_id):
    return 'python3 /home/ubuntu/mangosalad-desk/invest_cli.py status --report-id '+str(report_id)


def full_report(export, report_id, annotations=()):
    report = next((r for r in export['journal'] if r['id']==report_id and r['kind'] in ('research','review')), None)
    if report is None:
        raise ValueError('Historical report not found')
    return {'report':copy.deepcopy(report), 'context_review_notes':copy.deepcopy([a for a in annotations if a['report_id']==report_id])}


def project(state, annotations=()):
    """Keep factual data, old conditions and risks; index rather than repeat old prose."""
    result=copy.deepcopy(state)
    indexed=[]
    for report in state.get('reports', []):
        payload=report['payload']
        item={k:copy.deepcopy(v) for k,v in report.items() if k!='payload'}
        item['payload']={k:copy.deepcopy(payload[k]) for k in ('facts','orders','research_day','execution_day','rules_version','run_id','stage') if k in payload}
        item['review_status']=[{k:copy.deepcopy(v) for k,v in review.items() if k!='reason'} for review in payload.get('reviews', [])]
        item['analysis_index']={k:{'available':True,'characters':len(str(payload[k]))} for k in ('summary','inferences','uncertainties','counterevidence','next_plan') if k in payload}
        item['full_report_command']=report_reference(report['id'])
        indexed.append(item)
    result['reports']=indexed
    result['hypotheses']=[]
    for hypothesis in state.get('hypotheses', []):
        item={k:copy.deepcopy(v) for k,v in hypothesis.items() if k not in ('reason','sizing','resolution')}
        resolution=hypothesis.get('resolution')
        if resolution is not None:
            item['resolution']={k:copy.deepcopy(v) for k,v in resolution.items() if k!='reason'}
        item['full_report_command']=report_reference(hypothesis['report_id'])
        item['historical_analysis_available']=[k for k in ('reason','sizing') if k in hypothesis]
        result['hypotheses'].append(item)
    ids={r['id'] for r in indexed}|{h['report_id'] for h in result['hypotheses']}
    result['context_review_notes']=copy.deepcopy([a for a in annotations if a['report_id'] in ids])
    result['context_projection']={
        'version':1,
        'scope':'Only automatic model context; canonical history is unchanged.',
        'omitted_sections':'Historical analysis is indexed, not disproved or erased. Read the referenced full report before relying on or rejecting its rationale/counterevidence. Retained risk and facts are historical assertions, not current verified facts or rules.',
        'decision_boundary':'Review of an old hypothesis is separate from a new evidence-based decision; this projection prescribes no trade.'}
    return result
