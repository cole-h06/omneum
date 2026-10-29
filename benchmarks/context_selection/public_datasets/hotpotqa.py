"""HotpotQA distractor validation ingestion and official answer metrics."""

from collections import Counter
import re
import string


def load(path):
    import pyarrow.parquet as pq

    cases = []
    for item in pq.read_table(path).to_pylist():
        titles = item['context']['title']
        sentences = item['context']['sentences']
        if len(set(titles)) != len(titles):
            raise ValueError(f"duplicate context title: {item['id']}")
        chunks = [dict(chunk_id=f'p{i:02d}', document_id=title, title=title,
                       raw_text=''.join(parts), sentences=parts, source_url=None,
                       source_modified_at=None)
                  for i, (title, parts) in enumerate(zip(titles, sentences, strict=True))]
        facts = list(zip(item['supporting_facts']['title'],
                         item['supporting_facts']['sent_id'], strict=True))
        by_title = {c['title']: c for c in chunks}
        invalid_facts = [(title, index) for title, index in facts
                         if title not in by_title or not 0 <= index < len(by_title[title]['sentences'])]
        cases.append(dict(case_id=item['id'], dataset='hotpotqa', domain='wikipedia',
                          question=item['question'], answer=item['answer'],
                          question_type=item['type'], difficulty=item['level'], chunks=chunks,
                          relevant_document_ids=sorted({t for t, _ in facts}),
                          supporting_facts=facts, invalid_supporting_facts=invalid_facts,
                          retrieval_seconds=0.0))
    return cases


def normalize_answer(text):
    # HotpotQA v1: lowercase, remove ASCII punctuation/articles, collapse whitespace.
    text = ''.join(c for c in text.lower() if c not in string.punctuation)
    return ' '.join(re.sub(r'\b(a|an|the)\b', ' ', text).split())


def score_answer(prediction, reference):
    """Official normalized EM and token F1, including yes/no/noanswer guards."""
    prediction, reference = map(normalize_answer, (prediction, reference))
    exact = float(prediction == reference)
    special = {'yes', 'no', 'noanswer'}
    if (prediction in special or reference in special) and prediction != reference:
        return {'em': exact, 'f1': 0.0}
    a, b = prediction.split(), reference.split()
    overlap = sum((Counter(a) & Counter(b)).values())
    return {'em': exact, 'f1': 2 * overlap / (len(a) + len(b)) if overlap else 0.0}
