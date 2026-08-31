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

    print('meals of the day')
    slots = {}
    for meal in ('breakfast', 'lunch', 'dinner'):
        got = c.get(f'/api/recipes/browse?meal={meal}&limit=20').json()
        slots[meal] = got
        check(f'{meal} has dishes', got['total'] > 20, f"{got['total']:,}")
        shapes = {r['template'] for r in got['recipes']}
        check(f'{meal} shows a spread of shapes', len(shapes) >= 4,
              ','.join(sorted(shapes)))
    bfast = {r['template'] for r in slots['breakfast']['recipes']}
    dinner = {r['template'] for r in slots['dinner']['recipes']}
    check('no dinner shape turns up at breakfast',
          not (bfast & {'ragu', 'curry', 'traybake', 'braise', 'tagine'}),
          ','.join(sorted(bfast)))
    check('no breakfast shape turns up at dinner',
          not (dinner & {'porridge', 'smoothie', 'yoghurtbowl'}),
          ','.join(sorted(dinner)))

    print('diets')
    keto = c.get('/api/recipes/browse?diet=keto&limit=20').json()
    check('keto has dishes', keto['total'] > 50, f"{keto['total']:,}")
    worst = max((r['perServing']['c'] for r in keto['recipes']), default=999)
    check('keto stays low on carbohydrate', worst <= 40, f"worst {worst:.0f}g")
    banned = ('rice', 'pasta', 'potato', 'bread', 'oats', 'couscous',
              'noodles, dry', 'polenta', 'quinoa', 'barley', 'tortilla')
    bad = [r['name'] for r in keto['recipes']
           for i in r['ingredients']
           if any(b in i['food'].lower() for b in banned)
           and 'konjac' not in i['food'].lower()
           and 'zucchini' not in i['food'].lower()
           and 'cauliflower' not in i['food'].lower()]
    check('keto has no grain or starch bases', not bad, '; '.join(bad[:2]))

    vegan = c.get('/api/recipes/browse?diet=vegan&limit=20').json()
    check('vegan has dishes', vegan['total'] > 50, f"{vegan['total']:,}")
    # Whole words only: "eggplant" contains "egg" and is a vegetable.
    animal = {'chicken', 'beef', 'pork', 'lamb', 'salmon', 'tuna', 'prawns',
              'fish', 'eggs', 'yoghurt', 'milk', 'cheese', 'haloumi', 'whey',
              'turkey', 'butter', 'honey', 'oyster'}
    import re as _re
    slip = [f"{r['name']}: {i['food']}" for r in vegan['recipes']
            for i in r['ingredients']
            if set(_re.findall(r'[a-z]+', i['food'].lower())) & animal
            and 'butter beans' not in i['food'].lower()
            and 'peanut butter' not in i['food'].lower()]
    check('nothing from an animal in a vegan dish', not slip, '; '.join(slip[:2]))

    print('a planned day is a breakfast, a lunch and a dinner')
    r = c.post(f'/api/plans/{pid}/autoplan',
               json={'days': 7, 'meals_per_day': 3, 'ceiling': 2100,
                     'floor_protein': 150, 'floor_fibre': 30, 'apply': True})
    res = r.json()
    named = [[m.get('meal') for m in d['meals']] for d in res['days']]
    check('every day names its sittings',
          all(set(day) == {'breakfast', 'lunch', 'dinner'} for day in named),
          str(named[0]))

    lib = {x['id']: x for x in c.get('/api/recipes').json()['recipes']}
    breakfasts = [lib[m['recipeId']]['name'] for d in res['days']
                  for m in d['meals'] if m.get('meal') == 'breakfast'
                  and m['recipeId'] in lib]
    ragu_for_breakfast = [n for n in breakfasts
                          if any(w in n.lower() for w in
                                 ('ragu', 'curry', 'tray bake', 'braised'))]
    check('nobody is served ragu for breakfast', not ragu_for_breakfast,
          '; '.join(ragu_for_breakfast[:2]))

    print('saving and clearing the shopping list')
    plan = c.get(f'/api/plans/{pid}').json()['data']
    plan['shop'] = {'Broccoli, raw': {'aisle': 'produce', 'grams': 500}}
    plan['savedLists'] = {'Week one': {'savedAt': '2026-08-31',
                                       'shop': dict(plan['shop']), 'prices': {}}}
    c.put(f'/api/plans/{pid}', json={'data': plan})
    back = c.get(f'/api/plans/{pid}').json()['data']
    check('a saved list survives a round trip',
          list((back.get('savedLists') or {}).keys()) == ['Week one'])
    plan2 = dict(back)
    plan2['shop'] = {}
    c.put(f'/api/plans/{pid}', json={'data': plan2})
    check('clearing empties the list',
          not c.get(f'/api/plans/{pid}').json()['data']['shop'])
    c.post(f'/api/plans/{pid}/undo')
    check('undo brings the cleared list back',
          bool(c.get(f'/api/plans/{pid}').json()['data']['shop']))

print()
print('FAILED: ' + ', '.join(fails) if fails else 'all checks passed')
sys.exit(1 if fails else 0)
