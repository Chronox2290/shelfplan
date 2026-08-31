"""The four things asked for, checked end to end against the running app."""
import os
import sys
import tempfile

os.environ["DATABASE_URL"] = "sqlite:///" + tempfile.mktemp(suffix=".db").replace(chr(92), "/")
os.environ["SESSION_SECRET"] = "t"
os.environ["COOKIE_SECURE"] = "0"
os.environ["SIGNUP_MODE"] = "open"
sys.path.insert(0, os.path.join("C:" + os.sep, "Users", "chris", "coles-woolworths-mcp-server"))
from fastapi.testclient import TestClient
from webapp.app import app

fails = []


def check(name, ok, detail=''):
    print(f"  {'ok  ' if ok else 'FAIL'} {name}{'  ' + detail if detail else ''}")
    if not ok:
        fails.append(name)


with TestClient(app) as c:
    c.post('/api/auth/register',
           json={'email': 'newfeat@example.com', 'password': 'a-long-enough-password'})
    plan = c.post('/api/plans', json={'name': 'T', 'data': {}}).json()
    pid = plan['id']

    print('the recipe book')
    r = c.get('/api/recipes/browse?cuisine=japanese&limit=12')
    check('browse responds', r.status_code == 200, str(r.status_code))
    b = r.json()
    check('japanese has over 100 dishes', b['total'] > 100, f"{b['total']:,}")
    check('a page comes back full', b['count'] == 12, str(b['count']))
    names = [x['name'] for x in b['recipes']]
    check('names are distinct', len(set(names)) == 12)
    shapes = {x['template'] for x in b['recipes']}
    check('more than one shape on a page', len(shapes) > 2, ','.join(sorted(shapes)))

    seen = set()
    for cuisine in ('italian', 'japanese', 'chinese', 'thai', 'indian', 'greek',
                    'mexican', 'irish', 'middle-eastern'):
        got = c.get(f'/api/recipes/browse?cuisine={cuisine}&limit=100').json()
        check(f'{cuisine} yields 100', got['count'] == 100 and got['total'] >= 100,
              f"{got['count']} of {got['total']:,}")
        seen |= {x['name'] for x in got['recipes']}
    check('900 distinct dishes across the themes', len(seen) == 900, str(len(seen)))

    print('paging never repeats')
    p1 = c.get('/api/recipes/browse?cuisine=greek&limit=20&offset=0').json()
    p2 = c.get('/api/recipes/browse?cuisine=greek&limit=20&offset=20').json()
    ids1 = {x['id'] for x in p1['recipes']}
    ids2 = {x['id'] for x in p2['recipes']}
    check('pages do not overlap', not (ids1 & ids2))

    print('pictures')
    r = c.get('/api/food-images')
    check('images endpoint responds', r.status_code == 200)
    imgs = r.json()
    check('it names every ingredient it can', imgs['of'] > 80, str(imgs['of']))

    print('planning a week from nothing')
    lib = c.get('/api/recipes').json()['recipes']
    check('library starts empty', len(lib) == 0, str(len(lib)))
    r = c.post(f'/api/plans/{pid}/autoplan',
               json={'days': 7, 'meals_per_day': 3, 'ceiling': 2100,
                     'floor_protein': 150, 'floor_fibre': 30,
                     'apply': True, 'cuisine': 'any'})
    check('autoplan responds', r.status_code == 200, r.text[:120])
    res = r.json()
    check('seven days planned', len(res.get('days') or []) == 7,
          str(len(res.get('days') or [])))
    check('it cooked what was missing', len(res.get('library') or []) >= 6,
          str(len(res.get('library') or [])))
    check('most days hit the targets', res.get('daysMeetingTargets', 0) >= 5,
          f"{res.get('daysMeetingTargets')}/7")
    check('it was written into the plan', res.get('applied') is True)

    data = c.get(f'/api/plans/{pid}').json()['data']
    week = data.get('week') or []
    check('the plan holds seven days', len(week) == 7, str(len(week)))
    check('every day has meals', all(d.get('meals') for d in week))
    check("the day's targets were remembered",
          (data.get('meta') or {}).get('floorP') == 150)

    saved = c.get('/api/recipes').json()['recipes']
    check('the dishes are in the library to rate or delete', len(saved) >= 6,
          str(len(saved)))

    print('rebalancing one meal')
    r = c.post('/api/rebalance', json={
        'ingredients': [{'food': 'Red kidney beans, drained', 'gramsPerServing': 150},
                        {'food': 'Chicken breast, raw', 'gramsPerServing': 150}],
        'food': 'Red kidney beans, drained', 'grams': 100, 'target': 'p'})
    check('rebalance responds', r.status_code == 200, r.text[:120])

print()
print('FAILED: ' + ', '.join(fails) if fails else 'all checks passed')
sys.exit(1 if fails else 0)
