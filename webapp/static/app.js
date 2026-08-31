'use strict';

const $ = (id) => document.getElementById(id);
const state = { user: null, plans: [], planId: null, plan: null, tab: 'week', busy: false };

/* ---------------------------------------------------------------- helpers */

async function api(path, options = {}) {
  const res = await fetch('/api' + path, {
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    ...options,
    body: options.body ? JSON.stringify(options.body) : undefined,
  });
  let payload = null;
  try { payload = await res.json(); } catch (_) { /* empty body */ }
  if (!res.ok) {
    const detail = payload && payload.detail;
    // The status and the detail travel with the error. Without them a caller
    // that wants to handle one particular failure -- a save that lost a race,
    // say -- has only the message to go on, and cannot tell a conflict from
    // anything else that went wrong.
    const err = new Error(
      typeof detail === 'string' ? detail
        : (detail && detail.message) || 'Request failed (' + res.status + ')');
    err.status = res.status;
    err.detail = detail;
    throw err;
  }
  return payload;
}

const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g,
  (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

const money = (n) => (n == null || isNaN(n)) ? '—' : '$' + Number(n).toFixed(2);

function perKg(entry) {
  if (!entry || !entry.pack || !entry.price) return null;
  return entry.price / (entry.pack / 1000);
}

function latestPrice(food) {
  const list = (state.plan && state.plan.data && state.plan.data.prices || {})[food];
  return (list && list.length) ? list[list.length - 1] : null;
}

function deltaCell(now, before) {
  if (now == null || before == null || !before) return '<td class="r muted">—</td>';
  const pct = (now - before) / before * 100;
  if (Math.abs(pct) < 0.05) return '<td class="r muted num">±0%</td>';
  const cls = pct > 0 ? 'up' : 'down';
  return `<td class="r num ${cls}">${pct > 0 ? '+' : ''}${pct.toFixed(1)}%</td>`;
}

function describeAge(hours) {
  if (hours == null) return 'recently';
  if (hours < 1) return 'just now';
  if (hours < 24) return Math.round(hours) + 'h ago';
  const days = Math.floor(hours / 24);
  return days === 1 ? 'yesterday' : days + ' days ago';
}

/* ------------------------------------------------------------------- auth */

let authMode = 'login';
let authConfig = { inviteRequired: false, signupMode: 'open', minPasswordLength: 10 };

function renderAuthMode() {
  const login = authMode === 'login';
  const closed = authConfig.signupMode === 'closed';
  $('authTitle').textContent = login ? 'Sign in' : 'Create an account';
  $('authSub').textContent = login
    ? 'Your plan and price history sync to your account.'
    : `Pick a password of at least ${authConfig.minPasswordLength} characters.`;
  $('authGo').textContent = login ? 'Sign in' : 'Create account';
  $('authSwitchText').textContent = login ? 'No account yet?' : 'Already have one?';
  $('authSwitch').textContent = login ? 'Create one' : 'Sign in';
  $('password').autocomplete = login ? 'current-password' : 'new-password';
  $('authErr').classList.add('hide');
  // Only ask for an invite when registering on a server that wants one.
  $('inviteRow').classList.toggle('hide', login || !authConfig.inviteRequired);
  // Nothing to switch to when the server has registration turned off.
  $('authSwitch').parentElement.classList.toggle('hide', closed && login);
}

$('authSwitch').addEventListener('click', (e) => {
  e.preventDefault();
  authMode = authMode === 'login' ? 'register' : 'login';
  renderAuthMode();
});

$('authGo').addEventListener('click', async () => {
  const email = $('email').value.trim();
  const password = $('password').value;
  if (!email || !password) return;
  $('authGo').disabled = true;
  try {
    const body = { email, password };
    if (authMode === 'register' && authConfig.inviteRequired) {
      body.invite = $('invite').value.trim();
    }
    state.user = await api('/auth/' + (authMode === 'login' ? 'login' : 'register'),
      { method: 'POST', body });
    $('password').value = '';
    await boot();
  } catch (err) {
    const box = $('authErr');
    box.textContent = err.message;
    box.classList.remove('hide');
  } finally {
    $('authGo').disabled = false;
  }
});

$('password').addEventListener('keydown', (e) => { if (e.key === 'Enter') $('authGo').click(); });

$('signOut').addEventListener('click', async () => {
  await api('/auth/logout', { method: 'POST' });
  state.user = null; state.plan = null; state.planId = null; state.plans = [];
  showAuth();
});

function showAuth() {
  $('authView').classList.remove('hide');
  $('appView').classList.add('hide');
  $('userBox').classList.add('hide');
  $('planPicker').classList.add('hide');
  renderAuthMode();
}

/* ------------------------------------------------------------------ plans */

$('planSelect').addEventListener('change', async (e) => {
  state.planId = Number(e.target.value);
  await loadPlan();
  render();
});

$('newPlan').addEventListener('click', async () => {
  const name = prompt('Name for the new plan?', 'New plan');
  if (!name) return;
  const created = await api('/plans', { method: 'POST', body: { name, data: emptyPlan() } });
  state.planId = created.id;
  await loadPlans();
  await loadPlan();
  render();
});

$('renamePlan').addEventListener('click', async () => {
  const current = (state.plans.find((p) => p.id === state.planId) || {}).name || '';
  const name = (prompt('Rename this plan to?', current) || '').trim();
  if (!name || name === current) return;
  try {
    await api('/plans/' + state.planId, { method: 'PUT', body: { name } });
    await loadPlans();
    toast(`Renamed to "${name}".`);
  } catch (err) {
    toast(err.message);
  }
});

$('deletePlan').addEventListener('click', async () => {
  const plan = state.plans.find((p) => p.id === state.planId);
  if (!plan) return;
  // Everything in a plan goes with it -- the week, the shopping list, the
  // price history, the saved lists -- and none of that is covered by Undo,
  // which only reaches back through versions of a plan that still exists.
  if (!window.confirm(`Delete the plan "${plan.name}"?\n\nIts week, shopping `
    + 'list, saved lists and price history go with it. This cannot be undone. '
    + 'Your recipe library is kept.')) return;
  try {
    await api('/plans/' + state.planId, { method: 'DELETE' });
    state.planId = null;
    state.plan = null;
    await loadPlans();
    if (!state.plans.length) {
      const made = await api('/plans', { method: 'POST',
        body: { name: 'My plan', data: emptyPlan() } });
      state.planId = made.id;
      await loadPlans();
    }
    await loadPlan();
    toast(`Deleted "${plan.name}".`);
    render();
  } catch (err) {
    toast(err.message);
  }
});

function emptyPlan() {
  return { meta: { title: 'New plan' }, foods: {}, shop: {}, prices: {},
           aisles: ['produce', 'meat', 'fridge', 'pantry', 'freezer'],
           recipes: [], days: [], swaps: {}, equiv: {} };
}

async function loadPlans() {
  const res = await api('/plans');
  state.plans = res.plans;
  const sel = $('planSelect');
  sel.innerHTML = state.plans.map((p) =>
    `<option value="${p.id}">${esc(p.name)}</option>`).join('');
  if (!state.planId && state.plans.length) state.planId = state.plans[0].id;
  if (state.planId) sel.value = String(state.planId);
  $('planPicker').classList.toggle('hide', state.plans.length === 0);
}

async function loadPlan() {
  if (!state.planId) { state.plan = null; return; }
  state.plan = await api('/plans/' + state.planId);
}

async function savePlan() {
  if (!state.plan) return;
  // Say which version this page was working from. If something else has
  // written since -- the other device, another tab, the weekly price check --
  // the server refuses rather than letting this copy flatten it.
  try {
    const saved = await api('/plans/' + state.planId, {
      method: 'PUT',
      body: { data: state.plan.data, base_version: state.plan.version },
    });
    state.plan.version = saved.version;
    return;
  } catch (err) {
    if (err.status !== 409) throw err;
  }

  // Take the newer document and put this change back on top of it. Reloading
  // alone would drop whatever the person just did, which is the thing worth
  // protecting -- they are usually standing in a shop.
  const mine = state.plan.data;
  await loadPlan();
  state.plan.data = mergePlans(state.plan.data, mine);
  const saved = await api('/plans/' + state.planId, {
    method: 'PUT',
    body: { data: state.plan.data, base_version: state.plan.version },
  });
  state.plan.version = saved.version;
  toast('This plan had changed elsewhere; your change was merged in.');
}

// Their copy is the base -- it is the newer one -- and this page's own edits
// go on top. Ticked items are unioned rather than replaced, because two people
// shopping from one list are each right about what they have picked up.
function mergePlans(theirs, mine) {
  const merged = { ...theirs, ...mine };
  merged.prices = { ...(mine.prices || {}), ...(theirs.prices || {}) };
  merged.got = [...new Set([...(theirs.got || []), ...(mine.got || [])])];
  return merged;
}

/* A one-line report that does not need a place on the page to live. Errors
   used to be pushed into whichever div happened to be nearby, which meant the
   ones raised from a dialog had nowhere to go at all. */

let toastTimer = null;

function toast(message, kind) {
  let bar = $('toastBar');
  if (!bar) {
    bar = document.createElement('div');
    bar.id = 'toastBar';
    document.body.appendChild(bar);
  }
  bar.className = 'toast' + (kind ? ' ' + kind : '') + ' up';
  bar.textContent = String(message || '');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => bar.classList.remove('up'), 4200);
}


/* An image that fails to load ---------------------------------------------

   These fallbacks were written as onerror="..." attributes with the glyph
   pushed through JSON.stringify -- which emits its own double quotes, inside
   an attribute already delimited by double quotes. The attribute ended early
   and the browser parsed the remainder as a second attribute named
   `🥦"}))"`, so nothing ever fell back: a store URL that had expired showed
   the broken-image icon and stayed that way.

   One listener instead, and no JavaScript in markup at all. Image load
   failures do not bubble, so it has to listen in the capture phase. */

document.addEventListener('error', (event) => {
  const el = event.target;
  if (!(el instanceof HTMLImageElement)) return;
  if (el.dataset.onfail === 'remove') {
    el.remove();
    return;
  }
  if (el.dataset.onfail !== 'glyph') return;
  const tile = document.createElement(el.dataset.failTag || 'div');
  tile.className = el.dataset.failClass || '';
  tile.textContent = el.dataset.failMark || '';
  tile.setAttribute('aria-hidden', 'true');
  el.replaceWith(tile);
}, true);


/* ------------------------------------------------------------------- tabs */

document.querySelectorAll('nav.tabs button').forEach((btn) => {
  btn.addEventListener('click', () => {
    state.tab = btn.dataset.tab;
    document.querySelectorAll('nav.tabs button').forEach((b) =>
      b.setAttribute('aria-selected', String(b === btn)));
    render();
  });
});

/* ----------------------------------------------------------------- render */

function render() {
  const host = $('panels');
  if (!state.plan) {
    host.innerHTML = `<div class="card"><h2>No plan yet</h2>
      <p class="sub">Create one above, or import an existing plan from the Data tab.</p></div>`;
    return;
  }
  const views = { week: viewWeek, build: viewBuild, shop: viewShop,
                  prices: viewPrices, search: viewSearch, findrec: viewFind,
                  recipes: viewRecipes, own: viewOwn, data: viewData };
  host.innerHTML = (views[state.tab] || viewWeek)();
  if (state.tab === 'search') wireSearch();
  if (state.tab === 'shop') wireShop();
  if (state.tab === 'data') wireData();
  if (state.tab === 'prices') wirePrices();
  if (state.tab === 'build') wireBuild();
  if (state.tab === 'week') { wireAuto(); wireWeek(); wireCookSheet(); }
  if (state.tab === 'recipes') { wireBook(); wireRecipes(); }
  if (state.tab === 'findrec') wireFindRecipe();
  if (state.tab === 'own') wireOwn();
}




function refreshSummary(res) {
  const moves = (res.changes || [])
    .filter((c) => c.perKg != null && c.previousPerKg)
    .map((c) => ({ ...c, pct: (c.perKg - c.previousPerKg) / c.previousPerKg * 100 }))
    .filter((c) => Math.abs(c.pct) >= 5)
    .sort((a, b) => Math.abs(b.pct) - Math.abs(a.pct));

  const movesHtml = moves.length ? `<table style="margin-top:10px"><thead><tr>
      <th>Moved</th><th class="r">Was</th><th class="r">Now</th><th class="r">Change</th></tr></thead>
    <tbody>${moves.map((m) => `<tr><td>${esc(m.food)}</td>
      <td class="r num">${money(m.previousPerKg)}</td>
      <td class="r num">${money(m.perKg)}</td>
      <td class="r num ${m.pct > 0 ? 'up' : 'down'}">${m.pct > 0 ? '+' : ''}${m.pct.toFixed(1)}%</td>
      </tr>`).join('')}</tbody></table>` : '';

  const review = (res.review || []).length ? `<div class="note" style="margin-top:10px">
    <strong>${res.review.length} held back for you to check.</strong> These were not applied.
    <ul style="margin:8px 0 0;padding-left:20px">${res.review.map((r) =>
      `<li>${esc(r.food)} — ${esc((r.reasons || []).join('; '))}${
        r.matched ? ` <span class="muted">(matched: ${esc(r.matched)})</span>` : ''}</li>`).join('')}</ul></div>` : '';

  return `<div class="note"><strong>Updated ${res.applied} items.</strong>
    ${res.heldBack ? res.heldBack + ' held back.' : ''}</div>${movesHtml}${review}`;
}







/* ---------------------------------------------------------- recipe builder */

let lastBuild = null;

function viewBuild() {
  return `<div class="card">
    <h2>Recipe builder</h2>
    <p class="sub">Composes meals to your targets, then prices every ingredient at
      both Woolworths and Coles.</p>
    <div class="grid g2">
      <div><label for="bMeals">Meals</label><input id="bMeals" type="number" value="5" min="1" max="14"></div>
      <div><label for="bServ">Servings each</label><input id="bServ" type="number" value="4" min="1" max="20"></div>
      <div><label for="bKcal">Calories per serving</label><input id="bKcal" type="number" value="600" min="150" max="2000"></div>
      <div><label for="bProt">Protein per serving (g)</label><input id="bProt" type="number" value="40" min="5" max="200"></div>
      <div><label for="bMealShare">Size it for</label>
        <select id="bMealShare">
          <option value="">Whatever I typed above</option>
          <option value="breakfast">A breakfast (a quarter of the day)</option>
          <option value="lunch">A lunch (a third)</option>
          <option value="dinner">A dinner (two fifths)</option>
        </select></div>
      <div><label for="bCuisine">Theme</label><select id="bCuisine">
        ${(state.cuisines || [{ id: 'any', label: 'No theme' }]).map((c) =>
          `<option value="${esc(c.id)}">${esc(c.label)}</option>`).join('')}
      </select></div>
      <div><label for="bDiet">Diet</label>
        <select id="bDiet">${optionsFor(DIETS, 'any')}</select></div>
      <div><label for="bMeal">Meal</label>
        <select id="bMeal">${optionsFor(MEALS, '')}</select></div>
      <div><label for="bExcl">Exclude (comma separated)</label>
        <input id="bExcl" placeholder="e.g. mushrooms, tofu"></div>
    </div>
    <div class="row" style="margin-top:14px">
      <button id="bGo" class="primary">Build and price</button>
      <button id="bOpts">Offer me choices</button>
      <button id="bSave" disabled>Save to plan</button>
    </div>
    <p class="muted small" style="margin:8px 0 0">
      <b>Build and price</b> makes a full week and costs it.
      <b>Offer me choices</b> proposes a few different meals so you can pick.
      <b>Size it for</b> takes your day's numbers below and works out that
      meal's share of them, since breakfast is not the same size as dinner.</p>
    ${goalPanel()}
    <div id="bOut" style="margin-top:16px"></div></div>`;
}

// A day's numbers from a goal and a bodyweight, rather than a figure per meal
// picked out of the air. Whether the day is split evenly or shaped is left to
// the person: cooking one dish to eat three times is a real way to eat, and so
// is a small breakfast and a proper dinner.
const goal = {
  profile: 'maintain',
  weight: 80,
  even: false,
  data: null,
};

function goalPanel() {
  const list = (goal.data && goal.data.profiles) || [];
  const chosen = list.find((p) => p.id === goal.profile);
  const t = chosen && chosen.targets;
  return `<div class="goal-panel">
    <div class="row">
      <div style="flex:2;min-width:180px">
        <label for="gProfile">What are you eating for?</label>
        <select id="gProfile">${list.length
          ? list.map((p) => `<option value="${esc(p.id)}"${
              p.id === goal.profile ? ' selected' : ''}>${esc(p.label)}</option>`).join('')
          : '<option>Loading…</option>'}</select>
      </div>
      <div style="flex:1;min-width:110px">
        <label for="gWeight">Your weight (kg)</label>
        <input id="gWeight" type="number" value="${goal.weight}" min="30" max="250">
      </div>
      <div style="flex:1;min-width:150px">
        <label for="gEven">The day</label>
        <select id="gEven">
          <option value=""${goal.even ? '' : ' selected'}>Breakfast smaller than dinner</option>
          <option value="1"${goal.even ? ' selected' : ''}>Every meal the same size</option>
        </select>
      </div>
    </div>
    ${t ? `<p class="muted small" style="margin:8px 0 0">${esc(chosen.note)}
      That is <b>${Math.round(t.ceiling)} kcal</b>, <b>${Math.round(t.floorP)}g
      protein</b> and <b>${Math.round(t.floorF)}g fibre</b> a day
      ${goal.even
        ? `&mdash; ${Math.round(t.ceiling / 3)} kcal a meal across three.`
        : `&mdash; about ${Math.round(t.ceiling * 0.25)} / ${
            Math.round(t.ceiling * 0.35)} / ${Math.round(t.ceiling * 0.40)} kcal
           across breakfast, lunch and dinner.`}
      <button class="ghost tiny" id="gApply">Use these</button></p>
      <p class="muted small" style="margin:6px 0 0">Published ranges, not
        advice. If someone is coaching you, their numbers win.</p>` : ''}
  </div>`;
}

// What one meal should be built to. With a sitting chosen it is that sitting's
// share of the day; otherwise it is whatever was typed, which is what somebody
// wanting a flat 600 a meal is asking for.
function mealSizedTargets() {
  const typed = {
    kcal_per_serving: Number(($('bKcal') || {}).value) || 600,
    protein_per_serving: Number(($('bProt') || {}).value) || 40,
  };
  const sitting = ($('bMealShare') || {}).value;
  const chosen = ((goal.data || {}).profiles || [])
    .find((p) => p.id === goal.profile);
  if (!sitting || !chosen) return typed;
  const share = goal.even ? 1 / 3
    : ({ breakfast: 0.25, lunch: 0.35, dinner: 0.40 })[sitting];
  return {
    kcal_per_serving: Math.round(chosen.targets.ceiling * share),
    protein_per_serving: Math.round(chosen.targets.floorP * share),
  };
}


async function loadGoals() {
  try {
    goal.data = await api('/profiles?weight=' + encodeURIComponent(goal.weight));
    render();
  } catch (_) { /* the builder still works with numbers typed in */ }
}

function wireGoals() {
  const profile = $('gProfile');
  if (profile) profile.addEventListener('change', () => {
    goal.profile = profile.value;
    render();
  });
  const weight = $('gWeight');
  if (weight) weight.addEventListener('change', () => {
    goal.weight = Math.max(30, Math.min(250, Number(weight.value) || 80));
    loadGoals();
  });
  const even = $('gEven');
  if (even) even.addEventListener('change', () => {
    goal.even = !!even.value;
    render();
  });
  const apply = $('gApply');
  if (apply) apply.addEventListener('click', () => {
    const chosen = ((goal.data || {}).profiles || [])
      .find((p) => p.id === goal.profile);
    if (!chosen) return;
    // Write the day's numbers into the plan, so the week planner and the day
    // bars agree with what the builder is building to.
    const meta = state.plan.data.meta || (state.plan.data.meta = {});
    meta.ceiling = chosen.targets.ceiling;
    meta.floorP = chosen.targets.floorP;
    meta.floorF = chosen.targets.floorF;
    meta.evenMeals = goal.even;
    savePlan().then(() => {
      toast(`Set to ${Math.round(chosen.targets.ceiling)} kcal and ${
        Math.round(chosen.targets.floorP)}g protein a day.`);
      render();
    }).catch((err) => toast(err.message));
  });
}


function wireBuild() {
  wireGoals();
  // Leaving the tab used to lose the whole build. Repaint it instead.
  if (lastBuild) {
    $('bOut').innerHTML = renderBuild(lastBuild);
    $('bSave').disabled = false;
  }
  const opts = $('bOpts');
  if (opts) opts.addEventListener('click', () => offerOptions());

  $('bGo').addEventListener('click', async () => {
    const btn = $('bGo');
    btn.disabled = true;
    btn.textContent = 'Building and pricing...';
    $('bOut').innerHTML = '<div class="note">Composing recipes, then checking both stores for every ingredient.</div>';
    try {
      const body = {
        seed: state.plan.name + ':' + Date.now(),
        meals: Number($('bMeals').value),
        servings: Number($('bServ').value),
        ...mealSizedTargets(),
        diet: $('bDiet').value,
        cuisine: ($('bCuisine') || {}).value || 'any',
        meal: ($('bMeal') || {}).value || '',
        exclude: $('bExcl').value.split(',').map((x) => x.trim()).filter(Boolean),
        price: true,
      };
      lastBuild = await api('/recipes/generate', { method: 'POST', body });
      $('bOut').innerHTML = renderBuild(lastBuild);
      $('bSave').disabled = false;
    } catch (err) {
      $('bOut').innerHTML = '<div class="err">' + esc(err.message) + '</div>';
    } finally {
      btn.disabled = false;
      btn.textContent = 'Build and price';
    }
  });

  $('bSave').addEventListener('click', async () => {
    if (!lastBuild) return;
    const res = await api('/recipes/save-many', { method: 'POST',
      body: { recipes: lastBuild.recipes } });

    const d = state.plan.data;
    d.shop = Object.fromEntries(Object.entries(lastBuild.shop).map(([food, line]) =>
      [food, { aisle: line.aisle, woo: line.woo, pack: line.pack,
               grams: line.grams, packsNeeded: line.packsNeeded }]));
    await savePlan();
    await loadPlan();
    await loadRecipes();
    $('bOut').innerHTML = `<div class="note">Saved ${res.saved} recipe${
      res.saved === 1 ? '' : 's'} to your library${
      res.skipped ? ` (${res.skipped} already there)` : ''}. Rate them in
      <b>Recipes</b>, or assign them to days in <b>Week</b>.</div>`
      + renderBuild(lastBuild);
  });
}

function renderBuild(res) {
  const totals = res.totals || { byStore: {} };
  const tiles = Object.entries(totals.byStore).map(([store, amount]) =>
    '<div class="stat"><div class="k">All at ' + esc(store) + '</div><div class="v">'
    + money(amount) + '</div></div>').join('');

  const cards = res.recipes.map((r) => {
    const m = r.perServing;
    const notes = (r.notes || []).map((n) =>
      '<div class="tag warn" style="margin-top:6px">' + esc(n) + '</div>').join('');
    return `<div class="day"><h3>${esc(r.name)}</h3>
      <div class="muted num" style="font-size:13px;margin-bottom:8px">
        ${m.kcal.toFixed(0)} kcal &middot; ${m.p.toFixed(0)}g protein &middot;
        ${m.c.toFixed(0)}g carb &middot; ${m.f.toFixed(0)}g fat &middot;
        ${m.fb.toFixed(0)}g fibre &mdash; per serving, ${r.servings} servings</div>
      ${r.ingredients.map((i) => '<div class="meal">' + esc(i.food)
        + '<span class="muted num"> ' + i.gramsPerServing + ' g</span></div>').join('')}
      <ol style="margin:10px 0 0;padding-left:20px;font-size:14px;color:var(--ink-2)">
        ${r.steps.map((st) => '<li>' + esc(st) + '</li>').join('')}</ol>${notes}</div>`;
  }).join('');

  const lines = Object.entries(res.shop || {}).map(([food, line]) => {
    const cells = ['woolworths', 'coles'].map((st) => {
      const v = (line.byStore || {})[st] || {};
      const win = line.cheapest === st;
      const flag = v.needsReview ? ' <span class="tag warn">check</span>' : '';
      return '<td class="r num' + (win ? ' down' : '') + '">'
        + (v.lineCost != null ? money(v.lineCost) : '&mdash;') + flag + '</td>';
    }).join('');
    return `<tr><td>${esc(food)}<div class="muted" style="font-size:12.5px">
      ${line.grams} g &middot; ${line.packsNeeded}&times; pack &middot; ${esc(line.aisle)}
      </div></td>${cells}<td class="r">${line.saving
        ? '<span class="tag ok">save ' + money(line.saving.perKg) + '/kg</span>' : ''}</td></tr>`;
  }).join('');

  return `<div class="stats">${tiles}
    <div class="stat"><div class="k">Cheapest per item</div>
      <div class="v">${money(totals.cheapestMixed)}</div></div></div>
    <div class="grid g2" style="margin-bottom:16px">${cards}</div>
    <h3 style="font-size:15px;margin:0 0 8px">Shopping list</h3>
    <div class="scroll"><table><thead><tr><th>Item</th>
      <th class="r">Woolworths</th><th class="r">Coles</th><th class="r"></th>
    </tr></thead><tbody>${lines}</tbody></table></div>
    <p class="muted" style="font-size:13px;margin-top:10px">
      Green is the cheaper store for that line. &ldquo;Cheapest per item&rdquo; assumes you
      split the shop between both; the store totals assume you buy everything at one.</p>`;
}

/* -------------------------------------------------------------------- pwa */

// Registration is best-effort: the app works fully without it, and service
// workers are unavailable over plain http on anything but localhost.
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js').catch(() => {});
  });
}

// Chrome and Edge fire this when the app is installable; iOS Safari never
// does, so the button simply stays hidden there and users add to the home
// screen from the share sheet.
let deferredInstall = null;
window.addEventListener('beforeinstallprompt', (e) => {
  e.preventDefault();
  deferredInstall = e;
  const btn = $('installBtn');
  if (btn) btn.style.display = 'inline-block';
});

const installBtn = $('installBtn');
if (installBtn) {
  installBtn.addEventListener('click', async () => {
    if (!deferredInstall) return;
    deferredInstall.prompt();
    await deferredInstall.userChoice;
    deferredInstall = null;
    installBtn.style.display = 'none';
  });
}

window.addEventListener('appinstalled', () => {
  deferredInstall = null;
  const btn = $('installBtn');
  if (btn) btn.style.display = 'none';
});

/* --------------------------------------------------------- password reset */

function showReset() {
  $('authView').classList.add('hide');
  $('appView').classList.add('hide');
  $('userBox').classList.add('hide');
  $('planPicker').classList.add('hide');
  $('resetView').classList.remove('hide');
}

// A reset link lands on /?reset=<token>.
function pendingResetToken() {
  try {
    return new URLSearchParams(window.location.search).get('reset');
  } catch (_) {
    return null;
  }
}

// Drop the token from the address bar so it does not linger in history,
// screenshots, or a shared URL.
function scrubResetToken() {
  try {
    window.history.replaceState({}, '', window.location.pathname);
  } catch (_) { /* not fatal */ }
}

const forgotLink = $('forgotLink');
if (forgotLink) {
  forgotLink.addEventListener('click', async (e) => {
    e.preventDefault();
    const email = $('email').value.trim();
    const box = $('authErr');
    if (!email) {
      box.textContent = 'Enter your email address first, then choose Forgot password.';
      box.classList.remove('hide');
      $('email').focus();
      return;
    }
    forgotLink.textContent = 'Sending...';
    try {
      const res = await api('/auth/forgot', { method: 'POST', body: { email } });
      box.className = 'note';
      box.textContent = res.message + (res.mailConfigured ? ''
        : ' This server has no mail configured, so the link is in its logs —'
          + ' ask whoever runs it.');
      box.classList.remove('hide');
    } catch (err) {
      box.className = 'err';
      box.textContent = err.message;
      box.classList.remove('hide');
    } finally {
      forgotLink.textContent = 'Forgot password?';
    }
  });
}

const resetGo = $('resetGo');
if (resetGo) {
  resetGo.addEventListener('click', async () => {
    const a = $('newPassword').value;
    const b = $('newPassword2').value;
    const box = $('resetErr');
    box.classList.add('hide');
    if (a !== b) {
      box.textContent = 'Those two passwords do not match.';
      box.classList.remove('hide');
      return;
    }
    const token = pendingResetToken();
    if (!token) {
      box.textContent = 'This page is missing its reset token. Open the link from your email again.';
      box.classList.remove('hide');
      return;
    }
    resetGo.disabled = true;
    try {
      await api('/auth/reset', { method: 'POST', body: { token, password: a } });
      scrubResetToken();
      $('resetView').classList.add('hide');
      await boot();
    } catch (err) {
      box.textContent = err.message;
      box.classList.remove('hide');
    } finally {
      resetGo.disabled = false;
    }
  });

  $('newPassword2').addEventListener('keydown',
    (e) => { if (e.key === 'Enter') resetGo.click(); });
}

/* ------------------------------------------------------- recipe library */

function stars(id, rating) {
  return [1, 2, 3, 4, 5].map((n) =>
    `<button class="star${n <= (rating || 0) ? ' on' : ''}" data-rate="${id}"
      data-n="${n}" title="${n} of 5" aria-label="Rate ${n} of 5">&#9733;</button>`
  ).join('') + (rating
    ? `<button class="ghost tiny" data-rate="${id}" data-n="0">clear</button>` : '');
}

function macroLine(m, servings) {
  if (!m) return '';
  return `<div class="macros num">
    <span><b>${Math.round(m.kcal)}</b> kcal</span>
    <span><b>${Math.round(m.p)}</b>g protein</span>
    <span><b>${Math.round(m.c)}</b>g carb</span>
    <span><b>${Math.round(m.f)}</b>g fat</span>
    <span><b>${Math.round(m.fb)}</b>g fibre</span>
    <span class="muted">per serving &middot; makes ${servings || '?'}</span>
  </div>`;
}

function recipeCard(r, opts) {
  const o = opts || {};
  const ing = (r.ingredients || []).map((i) => {
    const per = i.gramsPerServing != null ? `${i.gramsPerServing} g` : (i.qty || '');
    const tot = i.gramsTotal != null
      ? `<span class="muted"> (${i.gramsTotal} g total)</span>` : '';
    const food = i.food || i.name || '';
    return `<div class="meal ing-row">${foodPhoto(food, 'small', i.image)}
      <span class="ing-name">${esc(food)}</span>
      <span class="num">${esc(per)}</span>${tot}</div>`;
  }).join('');

  // In a grid of cards the method is what makes one three times the height of
  // its neighbour, and it is not what you are scanning for -- you are looking
  // for something to cook, and you read the method once you have chosen. So it
  // folds away in the library and stays open where a single recipe is the
  // whole point of the page.
  const fold = o.library;
  const steps = (r.steps || []).length
    ? (fold
      ? `<details class="fold"><summary><h4>Method</h4>
           <span class="muted small">${r.steps.length} steps</span></summary>
         <ol class="steps">${r.steps.map((st) => `<li>${esc(st)}</li>`).join('')}</ol>
         </details>`
      : `<h4>Method</h4><ol class="steps">${
          r.steps.map((st) => `<li>${esc(st)}</li>`).join('')}</ol>`) : '';

  const reheatBody = `${r.storage ? `<p class="muted small">${esc(r.storage)}</p>` : ''}
       <ul class="steps">${(r.reheat || []).map((t) => `<li>${esc(t)}</li>`).join('')}</ul>`;
  const reheat = (r.reheat || []).length
    ? (fold
      ? `<details class="fold"><summary><h4>Storing and reheating</h4></summary>
         ${reheatBody}</details>`
      : `<h4>Storing and reheating</h4>${reheatBody}`) : '';

  // A saved recipe carries notes as the one string you typed; a freshly built
  // one carries the builder's list of what it could not quite hit. Calling
  // .trim() on the list threw, which is why "See it" in the book did nothing.
  const noteList = Array.isArray(r.notes)
    ? r.notes.filter(Boolean)
    : (String(r.notes || '').trim() ? [String(r.notes).trim()] : []);
  const notes = noteList.length
    ? `<div class="note small" style="margin-top:10px">${noteList
        .map((n) => `<div>${esc(n)}</div>`).join('')}</div>` : '';

  const controls = o.library ? `
      <div class="rating">${stars(r.id, r.rating)}</div>
      <div style="flex:1"></div>
      <span class="counter" title="How many times you have made this. Recipes cooked twice or more show under Favourites when planning a week.">
        <button class="ghost tiny" data-cooked="${r.id}" data-step="-1"
          ${r.timesCooked ? '' : 'disabled'} aria-label="One fewer">&minus;</button>
        <span class="num">cooked ${r.timesCooked || 0}&times;</span>
        <button class="ghost tiny" data-cooked="${r.id}" data-step="1"
          aria-label="One more">+</button>
      </span>
      <button class="ghost tiny danger" data-del="${r.id}">Delete</button>` : '';

  const add = o.pickable
    ? `<button class="tiny" data-add="${r.id}">Add to a day</button>` : '';

  const cat = CAT_ORDER.includes(r.category) ? r.category : 'other';
  const origin = { mine: 'yours', imported: '', built: 'built to targets' }[
    recipeSource(r)];
  const tags = [
    o.inWeek ? '<span class="tag ok">this week</span>' : '',
    mealTag(r),
    origin ? `<span class="tag">${esc(origin)}</span>` : '',
    r.cuisineLabel && r.cuisine !== 'any'
      ? `<span class="tag">${esc(r.cuisineLabel)}</span>` : '',
    r.source ? `<a class="tag" href="${esc(r.source)}" target="_blank"
      rel="noopener noreferrer">from ${esc(r.sourceName || 'the web')}</a>` : '',
    `<span class="tag">${esc(CAT_LABEL[cat])}</span>`,
  ].filter(Boolean).join(' ');

  return `<div class="recipe">
    <div class="recipe-head">
      <span class="dot cat-${esc(cat)}" title="${esc(CAT_LABEL[cat])}"
        style="margin-top:6px"></span>
      <h3 style="flex:1;min-width:0">${esc(r.name)}</h3>${add}
    </div>
    <div class="recipe-tags">${tags}</div>
    ${r.image ? `<img class="recipe-hero" src="${esc(
      /^https?:/i.test(r.image) && !/woolworths\.media|coles\.com\.au/.test(r.image)
        ? remoteImage(r.image) : r.image)}" alt=""
      data-onfail="remove">` : recipeStrip(r)}
    <div class="recipe-body">
      ${macroLine(r.perServing, r.servings)}
      <h4>Ingredients</h4>${ing}${steps}${reheat}${notes}
    </div>
    ${controls ? `<div class="recipe-foot">${controls}</div>` : ''}</div>`;
}

function weekRecipeIds() {
  const ids = new Set();
  if (!state.plan || !state.plan.data) return ids;
  weekData().forEach((day) => (day.meals || []).forEach((m) => {
    if (m.on !== false && m.recipeId != null) ids.add(Number(m.recipeId));
  }));
  return ids;
}

const WEEK_FILTER = [
  { id: '', label: 'Everything' },
  { id: 'week', label: 'In this week' },
];

const libView = { q: '', meal: '', cat: '', sort: 'best', from: '', week: '' };

// Three ways a recipe gets into the library, and they are worth telling apart:
// the ones you wrote are yours, the ones off a website belong to whoever wrote
// them, and the rest the builder made up to hit a number.
const SOURCES = [
  { id: '', label: 'Everything' },
  { id: 'mine', label: 'My recipes' },
  { id: 'imported', label: 'From the web' },
  { id: 'built', label: 'Built for me' },
];

function recipeSource(r) {
  if (r.ownRecipe) return 'mine';
  if (r.sourceUrl || r.source) return 'imported';
  return 'built';
}

const LIB_SORTS = [
  { id: 'best', label: 'Best rated first' },
  { id: 'name', label: 'Name, A to Z' },
  { id: 'cooked', label: 'Most cooked' },
  { id: 'kcal', label: 'Fewest calories' },
  { id: 'protein', label: 'Most protein' },
];

// The filtered, sorted library. The page and the delete button both read it,
// because a button that says "delete these 6" has to mean the same six that
// are on the screen -- two copies of this logic could drift, and the way you
// find out is by losing recipes.
function libShown() {
  const list = state.recipes || [];
  const needle = libView.q.trim().toLowerCase();
  const weekIds = weekRecipeIds();
  const shown = list.filter((r) => {
    if (libView.meal && !(r.meals || (r.meal ? [r.meal] : ['lunch', 'dinner']))
      .includes(libView.meal)) return false;
    if (libView.cat && categoryOf(r) !== libView.cat) return false;
    if (libView.from && recipeSource(r) !== libView.from) return false;
    if (libView.week === 'week' && !weekIds.has(r.id)) return false;
    if (!needle) return true;
    // Searching the ingredients too, because "what can I do with the mince in
    // the fridge" is the question a library actually gets asked.
    return r.name.toLowerCase().includes(needle)
      || (r.ingredients || []).some((i) =>
        String(i.food || '').toLowerCase().includes(needle));
  });

  const per = (r) => r.perServing || {};
  const byName = (a, b) => a.name.localeCompare(b.name, undefined,
    { sensitivity: 'base' });
  const sorters = {
    best: (a, b) => (b.rating || 0) - (a.rating || 0)
      || (b.timesCooked || 0) - (a.timesCooked || 0) || byName(a, b),
    name: byName,
    cooked: (a, b) => (b.timesCooked || 0) - (a.timesCooked || 0) || byName(a, b),
    kcal: (a, b) => (per(a).kcal || 0) - (per(b).kcal || 0) || byName(a, b),
    protein: (a, b) => (per(b).p || 0) - (per(a).p || 0) || byName(a, b),
  };
  return shown.sort(sorters[libView.sort] || sorters.best);
}


function viewRecipes() {
  const list = state.recipes || [];
  if (!list.length) {
    return `${bookPanel()}
      <div class="card"><h2>Nothing saved yet</h2>
      <p class="sub">Open the book above and save what you like, build to your
        targets in the <b>Recipe builder</b>, or write your own.</p></div>`;
  }

  const shown = libShown();
  const weekIds = weekRecipeIds();

  const counts = {};
  CAT_ORDER.forEach((c) => { counts[c] = list.filter(
    (r) => categoryOf(r) === c).length; });

  // Deleting what is on screen rather than "everything" -- the filters are
  // right there, so wanting rid of just the dear ones, or just the fish, is a
  // filter and a button rather than twenty separate confirmations.
  const filtered = shown.length !== list.length;
  return `${bookPanel()}
    <div class="card">
    <div class="row" style="align-items:baseline">
      <div style="flex:1;min-width:0">
        <h2 style="margin:0">Recipe library</h2>
        <p class="sub" style="margin:4px 0 0">${list.length} saved${
          filtered ? `, ${shown.length} shown` : ''}.</p>
      </div>
      ${shown.length ? `<button class="ghost danger" id="libDelete">${
        filtered ? `Delete these ${shown.length}` : `Delete all ${list.length}`
      }</button>` : ''}
    </div>
    <div class="row">
      <div style="flex:2;min-width:170px">
        <label for="libFind">Search</label>
        <input id="libFind" type="search" value="${esc(libView.q)}"
          placeholder="name or ingredient" autocomplete="off"></div>
      <div style="flex:1;min-width:130px">
        <label for="libMeal">Meal</label>
        <select id="libMeal">${optionsFor(MEALS, libView.meal)}</select></div>
      <div style="flex:1;min-width:130px">
        <label for="libFrom">Where from</label>
        <select id="libFrom">${optionsFor(SOURCES, libView.from)}</select></div>
      <div style="flex:1;min-width:130px">
        <label for="libWeek">This week</label>
        <select id="libWeek">${optionsFor(WEEK_FILTER, libView.week)}</select></div>
      <div style="flex:1;min-width:130px">
        <label for="libSort">Order</label>
        <select id="libSort">${optionsFor(LIB_SORTS, libView.sort)}</select></div>
    </div>
    <div class="chips">
      <button class="chip${libView.cat ? '' : ' on'}" data-libcat="">All</button>
      ${CAT_ORDER.filter((c) => counts[c]).map((c) =>
        `<button class="chip${libView.cat === c ? ' on' : ''}" data-libcat="${esc(c)}">
          <span class="dot cat-${esc(c)}"></span>${esc(CAT_LABEL[c])}
          <span class="muted">${counts[c]}</span></button>`).join('')}
    </div>
    ${shown.length
      ? `<div class="grid g2">${shown.map(
          (r) => recipeCard(r, { library: true, inWeek: weekIds.has(r.id) })).join('')}</div>`
      : '<p class="muted">Nothing matches those filters.</p>'}
  </div>`;
}

function wireRecipes() {
  const find = $('libFind');
  if (find) find.addEventListener('input', () => {
    libView.q = find.value;
    render();
    const again = $('libFind');
    if (again) {
      again.focus();
      again.setSelectionRange(again.value.length, again.value.length);
    }
  });
  const wipeLib = $('libDelete');
  if (wipeLib) wipeLib.addEventListener('click', async () => {
    const ids = libShown().map((r) => r.id);
    if (!ids.length) return;
    const what = ids.length === (state.recipes || []).length
      ? `all ${ids.length} saved recipes`
      : `the ${ids.length} recipes shown`;
    // Recipes are not covered by the plan's undo, so this one really is gone.
    if (!window.confirm(`Delete ${what}?

This cannot be undone. Days in `
      + 'your week that used them will say the recipe is missing.')) return;
    wipeLib.disabled = true;
    wipeLib.textContent = 'Deleting…';
    try {
      const res = await api('/recipes/delete-many', { method: 'POST', body: { ids } });
      await loadRecipes();
      toast(`Deleted ${res.deleted} recipe${res.deleted === 1 ? '' : 's'}.`);
    } catch (err) {
      toast(err.message);
    }
    render();
  });

  const week = $('libWeek');
  if (week) week.addEventListener('change', () => {
    libView.week = week.value;
    render();
  });

  const meal = $('libMeal');
  if (meal) meal.addEventListener('change', () => {
    libView.meal = meal.value;
    render();
  });
  const sort = $('libSort');
  if (sort) sort.addEventListener('change', () => {
    libView.sort = sort.value;
    render();
  });
  const from = $('libFrom');
  if (from) from.addEventListener('change', () => {
    libView.from = from.value;
    render();
  });
  document.querySelectorAll('[data-libcat]').forEach((b) => {
    b.addEventListener('click', () => {
      libView.cat = b.dataset.libcat;
      render();
    });
  });

  document.querySelectorAll('[data-rate]').forEach((b) => {
    b.addEventListener('click', async () => {
      const id = Number(b.dataset.rate);
      const n = Number(b.dataset.n);
      await api('/recipes/' + id, { method: 'PATCH',
        body: n === 0 ? { clear_rating: true } : { rating: n } });
      await loadRecipes();
      render();
    });
  });
  document.querySelectorAll('[data-cooked]').forEach((b) => {
    b.addEventListener('click', async () => {
      await api('/recipes/' + Number(b.dataset.cooked),
        { method: 'PATCH', body: { cooked: Number(b.dataset.step) } });
      await loadRecipes();
      render();
    });
  });
  document.querySelectorAll('[data-del]').forEach((b) => {
    b.addEventListener('click', async () => {
      const card = b.closest('.recipe');
      const name = card ? card.querySelector('h3').textContent : 'this recipe';
      if (!window.confirm(`Delete "${name}"? This cannot be undone.`)) return;
      await api('/recipes/' + Number(b.dataset.del), { method: 'DELETE' });
      await loadRecipes();
      render();
    });
  });
}

async function loadRecipes() {
  const res = await api('/recipes');
  state.recipes = res.recipes || [];
}

/* ------------------------------------------------------------ week plan */

const DAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday',
              'Saturday', 'Sunday'];

const CAT_LABEL = { chicken: 'Chicken', beef: 'Beef', pork: 'Pork',
                    lamb: 'Lamb', fish: 'Fish & seafood',
                    vegetarian: 'Vegetarian', other: 'Other' };
const CAT_ORDER = ['chicken', 'beef', 'pork', 'lamb', 'fish', 'vegetarian', 'other'];

const week = {
  picker: null,
  monday: null,
  // Seven days side by side is a lot to take in, and on a phone it is a lot to
  // scroll past. One day at a time, opening on today, is how you actually use
  // a plan -- you cook from it one day at a time.
  one: (() => {
    try { return localStorage.getItem('shelfplan.weekOne') === '1'; }
    catch (_) { return false; }
  })(),
  day: 0,
  // Whether each meal lists what goes in it. On by default: seeing the day is
  // the point of a plan, and a name on its own does not tell you what Tuesday
  // involves.
  detail: (() => {
    try { return localStorage.getItem('shelfplan.weekDetail') !== '0'; }
    catch (_) { return true; }
  })(),
};

// A day is judged against a ceiling you should stay under and floors you
// should get past -- which is how people actually eat, rather than hitting an
// exact number at every single meal.
const DEFAULT_GOALS = { ceiling: 2000, floorP: 140, floorF: 25 };

function goals() {
  const d = state.plan.data;
  d.meta = d.meta || {};
  const m = d.meta;
  return {
    ceiling: Number(m.ceiling) || DEFAULT_GOALS.ceiling,
    floorP: Number(m.floorP) || DEFAULT_GOALS.floorP,
    floorF: Number(m.floorF) || DEFAULT_GOALS.floorF,
  };
}

function weekData() {
  const d = state.plan.data;
  // Normalise to seven days WITHOUT discarding anything. The previous version
  // replaced the whole week whenever its length was not exactly seven, which
  // silently destroyed every planned meal and then persisted that on the next
  // save. Padding and preserving is the only safe way to reshape user data.
  const existing = Array.isArray(d.week) ? d.week : [];
  d.week = DAYS.map((name, i) => {
    const prior = existing[i] || existing.find((x) => x && x.day === name) || {};
    return { day: name, meals: Array.isArray(prior.meals) ? prior.meals : [] };
  });
  // Anything beyond seven days is kept rather than dropped, folded onto the
  // last day, so no meal disappears because a plan had an odd shape.
  existing.slice(7).forEach((extra) => {
    if (extra && Array.isArray(extra.meals) && extra.meals.length) {
      d.week[6].meals = d.week[6].meals.concat(extra.meals);
    }
  });
  // Meals gained an on/off switch; older plans predate it and are all "on".
  d.week.forEach((day) => day.meals.forEach((m) => {
    if (m.on === undefined) m.on = true;
  }));
  return d.week;
}

function recipeById(id) {
  return (state.recipes || []).find((r) => r.id === Number(id));
}

// A meal added by hand belongs to whichever sitting the day is still missing,
// so it lands in the right place rather than showing up unlabelled.
function sittingFor(dayIndex) {
  const day = weekData()[dayIndex] || { meals: [] };
  const taken = new Set((day.meals || []).map((m) => m.meal).filter(Boolean));
  return ['breakfast', 'lunch', 'dinner'].find((s) => !taken.has(s)) || 'lunch';
}


// Monday is 0 here, as the week is stored.
function todayIndex() {
  return (new Date().getDay() + 6) % 7;
}


function dayTotals(day) {
  const out = { kcal: 0, p: 0, c: 0, f: 0, fb: 0, meals: 0 };
  (day.meals || []).forEach((m) => {
    if (m.on === false) return;
    const r = recipeById(m.recipeId);
    if (!r || !r.perServing) return;
    const n = m.servings || 1;
    out.kcal += (r.perServing.kcal || 0) * n;
    out.p += (r.perServing.p || 0) * n;
    out.c += (r.perServing.c || 0) * n;
    out.f += (r.perServing.f || 0) * n;
    out.fb += (r.perServing.fb || 0) * n;
    out.meals += 1;
  });
  return out;
}

// A bar that reads at a glance: green when the day works, amber when it does
// not, with the number that matters spelled out underneath.
function goalBar(label, value, target, kind) {
  const pct = target ? Math.min(100, (value / target) * 100) : 0;
  const good = kind === 'ceiling' ? value <= target : value >= target;
  const gap = kind === 'ceiling' ? target - value : target - value;
  const detail = kind === 'ceiling'
    ? (good ? `${Math.round(gap)} to spare` : `${Math.round(-gap)} over`)
    : (good ? 'met' : `${Math.round(gap)} short`);
  return `<div class="goal ${good ? 'ok' : 'miss'}">
    <div class="goal-top"><span>${esc(label)}</span>
      <span class="num">${Math.round(value)}<span class="muted"> / ${target}</span></span></div>
    <div class="goal-track"><i style="width:${pct.toFixed(0)}%"></i></div>
    <div class="goal-note">${esc(detail)}</div>
  </div>`;
}

function viewWeek() {
  const data = weekData();
  const library = state.recipes || [];
  const g = goals();

  if (!library.length) {
    // An empty library is no longer a dead end: the planner composes what it
    // needs, so the panel that does that is exactly what belongs here.
    auto.show = true;
    return `${autoPanel()}
      <div class="card"><h2>Or build them yourself</h2>
      <p class="sub">Nothing saved yet. Plan the week above and it will cook the
        dishes to fill it, or build your own in the <b>Recipe builder</b>.</p></div>`;
  }

  if (!week.monday) week.monday = mondayOf(new Date());
  if (week.day == null) week.day = todayIndex();
  const from = new Date(week.monday);
  const to = dayDate(6);

  let weekKcal = 0;
  let meals = 0;
  let daysOk = 0;
  let daysPlanned = 0;

  const cards = data.map((day, di) => {
    const date = dayDate(di);
    const t = dayTotals(day);
    weekKcal += t.kcal;
    meals += t.meals;
    if (t.meals) {
      daysPlanned += 1;
      if (t.kcal <= g.ceiling && t.p >= g.floorP && t.fb >= g.floorF) daysOk += 1;
    }

    const rows = (day.meals || []).map((m, mi) => {
      const r = recipeById(m.recipeId);
      if (!r) {
        // A planned meal whose recipe has gone -- deleted, or belonging to
        // another plan. It used to render as nothing at all, so a day quietly
        // came up a meal short with no way to tell why.
        return `<div class="meal planned missing">
          <span class="meal-name">${m.meal
            ? `<span class="sitting">${esc(m.meal)}</span>` : ''}
            <span class="muted">This recipe is no longer in your library</span></span>
          <div class="meal-controls">
            <button class="ghost tiny" data-rm="${di}:${mi}"
              title="Remove">&times;</button></div>
        </div>`;
      }
      const per = r.perServing || {};
      const mult = m.servings || 1;
      const off = m.on === false;
      return `<div class="meal planned${off ? ' off' : ''}">
        <label class="tick" title="${off ? 'Skipped' : 'Eating this'}">
          <input type="checkbox" data-on="${di}:${mi}" ${off ? '' : 'checked'}>
          <span class="dot cat-${esc(categoryOf(r))}"></span>
          ${mealThumb(r)}
          <span class="meal-name">${m.meal
            ? `<span class="sitting">${esc(m.meal)}</span>` : ''}${esc(r.name)}</span></label>
        <div class="meal-controls">
          <input type="number" class="mult" data-mult="${di}:${mi}"
            value="${m.servings || 1}" min="0.1" max="9" step="0.1"
            title="Servings -- tenths are allowed, so a day can land on its
calorie target instead of stopping short of it">
          <button class="ghost tiny" data-mealswap="${di}:${mi}"
            title="Something else that eats about the same">swap</button>
          <button class="ghost tiny" data-rm="${di}:${mi}" title="Remove">&times;</button>
        </div>
        <div class="meal-macros num">
          <b>${Math.round((per.kcal || 0) * mult)}</b> kcal
          &middot; <b>${Math.round((per.p || 0) * mult)}</b> g protein
          &middot; <b>${Math.round((per.fb || 0) * mult)}</b> g fibre
        </div>
        ${week.detail ? mealIngredients(r, mult) : ''}
      </div>`;
    }).join('');

    const summary = t.meals ? `<div class="day-goals">
        ${goalBar('kcal', t.kcal, g.ceiling, 'ceiling')}
        ${goalBar('protein', t.p, g.floorP, 'floor')}
        ${goalBar('fibre', t.fb, g.floorF, 'floor')}
      </div>` : '';

    const dayLine = t.meals ? `<div class="day-line num">
        <span><b>${Math.round(t.kcal)}</b> kcal</span>
        <span class="${t.p >= g.floorP ? 'hit' : 'short'}"><b>${
          Math.round(t.p)}</b> g protein</span>
        <span><b>${Math.round(t.c || 0)}</b> g carb</span>
        <span><b>${Math.round(t.f || 0)}</b> g fat</span>
        <span class="${t.fb >= g.floorF ? 'hit' : 'short'}"><b>${
          Math.round(t.fb)}</b> g fibre</span>
      </div>` : '';

    return `<div class="day${isToday(date) ? ' today' : ''}">
      <h3><span>${esc(day.day)}</span><span class="muted num">${shortDate(date)}</span></h3>
      ${dayLine}
      ${rows || '<p class="muted small" style="margin:4px 0">Nothing planned.</p>'}
      ${summary}
      <button class="tiny add-day" data-pick="${di}">+ Add a meal</button>
    </div>`;
  });

  return `<div class="card">
    <div class="row"><div style="flex:1">
      <h2>Plan your week</h2>
      <p class="sub" style="margin:0">${shortDate(from)} &ndash; ${shortDate(to)}
        &middot; ${meals} meal${meals === 1 ? '' : 's'}</p></div>
      <button id="weekPrev" class="ghost" title="Previous week">&larr;</button>
      <button id="weekToday" class="ghost">This week</button>
      <button id="weekNext" class="ghost" title="Next week">&rarr;</button>
    </div>

    <div class="row goals-row">
      <span class="muted small">Each day:</span>
      <label class="muted small">under
        <input type="number" id="gCeiling" value="${g.ceiling}" min="800" max="6000"
          step="50" style="width:74px"> kcal</label>
      <label class="muted small">at least
        <input type="number" id="gFloorP" value="${g.floorP}" min="20" max="400"
          step="5" style="width:64px"> g protein</label>
      <label class="muted small">at least
        <input type="number" id="gFloorF" value="${g.floorF}" min="5" max="100"
          style="width:56px"> g fibre</label>
    </div>

    <div class="row" style="margin-top:12px">
      <button id="weekShop" class="primary">Build shopping list</button>
      <button id="autoOpen">Plan it for me</button>
      <button id="cookOpen">${cookSheet.show ? 'Hide the cook sheet' : 'Sunday cook sheet'}</button>
      <button id="weekDetail" class="ghost"
        title="Show what goes into each meal">${
        week.detail ? 'Hide ingredients' : 'Show ingredients'}</button>
      <button id="weekClear" class="ghost">Clear week</button>
      <button id="planUndo" class="ghost" title="Restore the previous version of this plan">Undo</button>
    </div>
    <div id="autoHost">${auto.show ? autoPanel() : ''}</div>
    <div id="cookHost">${cookSheet.show ? cookSheetPanel() : ''}</div>

    <div class="row day-nav">
      <div class="seg">
        <button class="${week.one ? '' : 'on'}" data-view="all">Whole week</button>
        <button class="${week.one ? 'on' : ''}" data-view="one">One day</button>
      </div>
      ${week.one ? `<div style="flex:1"></div>
        <button class="ghost" id="dayPrev" title="Previous day">&larr;</button>
        <b class="day-name">${esc(DAYS[week.day])}</b>
        <button class="ghost" id="dayNext" title="Next day">&rarr;</button>` : ''}
    </div>

    <div class="stats" style="margin-top:14px">
      <div class="stat"><div class="k">Days that work</div>
        <div class="v">${daysOk}<span class="muted" style="font-size:15px">/${daysPlanned || 0}</span></div></div>
      <div class="stat"><div class="k">Meals</div><div class="v">${meals}</div></div>
      <div class="stat"><div class="k">Week energy</div>
        <div class="v">${Math.round(weekKcal).toLocaleString()}</div></div>
    </div>
    <div id="weekOut"></div>
    <div class="calendar${week.one ? ' single' : ''}">${
      week.one ? cards[week.day] : cards.join('')}</div></div>`;
}





/* -------------------------------------------------------- shopping list */

// The two figures a shopping trip is actually watched by. Shared between the
// render and the tick handler so a checkbox click and a page reload can never
// disagree about what they add up to -- which is exactly the bug this
// replaced: ticking an item moved the count but left "still to get" frozen
// at whatever it read on load, in precisely the moment it was being watched.
function shopTotals(shop, got) {
  let total = 0, remaining = 0, unpriced = 0;
  Object.entries(shop).forEach(([food, meta]) => {
    const p = latestPrice(food);
    const packs = (meta && meta.packsNeeded) || 1;
    const cost = p && p.price ? p.price * packs : null;
    if (cost) {
      total += cost;
      if (!got.has(food)) remaining += cost;
    } else {
      unpriced += 1;
    }
  });
  return { total, remaining, unpriced };
}


function gotSet() {
  const d = state.plan.data;
  if (!Array.isArray(d.got)) d.got = [];
  return new Set(d.got);
}

// What to actually pick up. A cauliflower does not come in a one-kilogram
// pack, so "2 packs, 1000g each" is a costing unit printed as a shopping
// instruction. For anything sold by weight or by the each, say the weight.
// Supermarket product names end in their own pack size -- "Greek Style Yoghurt
// 2kg", "Bananas Kids 5 pack" -- and the ticket beside them says the unit. So
// the separate size line is usually the same fact a third time. Show it only
// when it adds something: not when the name already ends with it, and not when
// it is the bare unit the ticket is about to say anyway.
function packNote(product) {
  const size = (product.package_size || '').trim();
  if (!size) return '';
  const flat = size.toLowerCase().replace(/\s+/g, '');
  if (flat === 'each' || flat === 'ea' || flat === 'per each') return '';
  const name = (product.name || '').toLowerCase().replace(/\s+/g, '');
  return name.endsWith(flat) ? '' : size;
}


// A store product and a stored price reading spell the same three facts with
// different keys. The ticket only wants the three.
function ticketFrom(product) {
  if (!product) return null;
  return {
    price: product.pack_price != null ? product.pack_price : product.price,
    wasPrice: product.was_price != null ? product.was_price : product.wasPrice,
    onSpecial: product.on_special != null ? product.on_special : product.onSpecial,
  };
}


// The price as the shelf writes it: dollars large, cents raised beside them,
// the unit price in small print underneath, and the whole card red when it has
// moved. Everything a ticket says, in the order it says it.
function shelfTicket(price, perKg) {
  if (!price || !price.price) {
    return `<span class="ticket empty"><span class="ticket-price">&mdash;</span>
      <span class="ticket-unit">no price yet</span></span>`;
  }
  const was = price.wasPrice && price.wasPrice > price.price ? price.wasPrice : null;
  const special = !!(price.onSpecial || was);
  const [dollars, cents] = Number(price.price).toFixed(2).split('.');

  return `<span class="ticket${special ? ' special' : ''}">
    ${special ? '<span class="ticket-flag">SPECIAL</span>' : ''}
    <span class="ticket-price"><span class="ticket-sign">$</span>${dollars}<span
      class="ticket-cents">${cents}</span></span>
    <span class="ticket-unit">${perKg ? money(perKg) + ' per kg' : 'each'}${
      was ? ` &middot; was ${money(was)}` : ''}</span>
  </span>`;
}


function howMuch(food, meta, price) {
  const grams = Math.round(meta.grams || 0);
  if (!grams) return '';
  const weight = grams >= 1000
    ? `${(grams / 1000).toFixed(grams % 1000 ? 1 : 0)} kg`
    : `${grams} g`;

  const matched = String((price && price.matched) || '');
  const loose = meta.loose
    || / each$| each\b|bunch|loose/i.test(matched)
    || (LOOSE_LOOKING.has(food.split(',')[0].toLowerCase()) && !meta.pinned);
  if (loose) return weight;

  const packs = meta.packsNeeded || 1;
  return packs > 1 ? `${weight} &middot; ${packs} packs` : weight;
}

// A fallback for lines built before the flag existed, and for anything typed
// in by hand. Deliberately short: guessing wrongly here only costs the words
// "2 packs", so it errs towards the plain weight.
const LOOSE_LOOKING = new Set([
  'banana', 'bananas', 'cauliflower', 'broccoli', 'cabbage', 'capsicum',
  'zucchini', 'eggplant', 'cucumber', 'pumpkin', 'potato', 'sweet potato',
  'carrot', 'carrots', 'onion', 'brown onion', 'tomato', 'tomatoes', 'leek',
  'celery', 'lemon', 'lemons', 'garlic', 'avocado', 'kale', 'silverbeet',
  'asparagus', 'bok choy', 'brussels sprouts',
]);


function viewShop() {
  const d = state.plan.data;
  const shop = d.shop || {};
  const entries = Object.entries(shop);
  if (!entries.length) {
    return `<div class="card"><h2>Nothing on the list</h2>
      <p class="sub">Plan a week, or build recipes, then come back.</p></div>
      ${savedListsPanel()}`;
  }

  const got = gotSet();
  const aisles = (d.aisles && d.aisles.length ? d.aisles : [])
    .concat(['produce', 'meat', 'fridge', 'pantry', 'freezer', 'other']);
  const seen = new Set();
  const order = aisles.filter((a) => (seen.has(a) ? false : seen.add(a)));

  const byAisle = {};
  entries.forEach(([food, meta]) => {
    const a = (meta && meta.aisle) || 'other';
    (byAisle[a] = byAisle[a] || []).push([food, meta || {}]);
  });

  const totals = shopTotals(shop, got);
  const total = totals.total;
  const remaining = totals.remaining;
  const sections = order.concat(Object.keys(byAisle).filter((a) => !order.includes(a)))
    .filter((a) => byAisle[a])
    .map((aisle) => {
      const rows = byAisle[aisle].map(([food, meta]) => {
        const p = latestPrice(food);
        const kg = perKg(p);
        const ticked = got.has(food);
        const link = p && p.url
          ? ` <a href="${esc(p.url)}" target="_blank" rel="noopener noreferrer"
               title="Open at the store">&#8599;</a>` : '';
        const pic = meta.image || (p && p.image) || '';
        return `<tr class="${ticked ? 'got' : ''}">
          <td><div class="prod-row">
            ${thumb({ image: pic, name: food })}
            <div style="min-width:0"><label class="tick">
              <input type="checkbox" data-got="${esc(food)}"
              ${ticked ? 'checked' : ''}> <span class="shop-name">${esc(food)}</span></label>
            <div class="muted small">${howMuch(food, meta, p)}${
              p && p.matched ? ' &middot; ' + esc(p.matched) : ''}${link}</div>
            </div></div></td>

          <td class="r" data-label="Price">${shelfTicket(p, kg)}
            <button class="ghost tiny" data-edit="${esc(food)}"
              title="${p && p.price ? 'Correct this price' : 'Enter a price'}">${
              p && p.price ? 'edit' : 'set'}</button></td>
          <td class="r muted small" data-label="Store">${esc((p && p.store) || '')}
            <button class="ghost tiny" data-swap="${esc(food)}"
              title="Choose a different product for this line">swap</button>
            <button class="ghost tiny" data-drop="${esc(food)}" title="Remove from list">&times;</button></td>
        </tr>`;
      }).join('');
      return `<tr class="aisle-row"><td colspan="3" class="aisle">${esc(aisle)}</td></tr>` + rows;
    }).join('');

  return `<div class="card">
    <div class="row" style="margin-bottom:12px">
      <div style="flex:1"><h2>Shopping list</h2>
        <p class="sub" id="basketCount" style="margin:0">${got.size} of ${
          entries.length} in the basket</p></div>
      <button id="refreshBtn" class="primary">Refresh prices</button>
      <button id="saveList">Save this list</button>
      <button id="clearGot" class="ghost">Untick all</button>
      <button id="clearList" class="ghost danger">Clear list</button>
    </div>
    <div class="stats">
      <div class="stat"><div class="k">Basket total</div>
        <div class="v" id="shopTotalV">${money(total)}</div>
        ${totals.unpriced ? `<div class="muted small" id="shopTotalNote">+${
          totals.unpriced} item${totals.unpriced === 1 ? '' : 's'} not priced yet</div>` : ''}</div>
      <div class="stat"><div class="k">Still to get</div>
        <div class="v" id="shopRemainingV">${money(remaining)}</div></div>
      <div class="stat"><div class="k">Items</div><div class="v">${entries.length}</div></div>
    </div>
    <div id="refreshOut"></div>
    <div class="scroll"><table>
      <thead><tr><th>Item</th><th class="r">Price</th>
        <th class="r">Store</th></tr></thead>
      <tbody>${sections}</tbody></table></div></div>
    ${savedListsPanel()}`;
}

// Saved lists live in the plan alongside everything else, so they travel with
// an export and come back with an import rather than being stranded in one
// browser.
function savedLists() {
  const d = state.plan.data;
  d.savedLists = d.savedLists || {};
  return d.savedLists;
}

function savedListsPanel() {
  const saved = savedLists();
  const names = Object.keys(saved).sort();
  if (!names.length) return '';
  return `<div class="card">
    <h2>Saved lists</h2>
    <p class="sub">Restoring one replaces what is on the list now. Undo is on
      the Data tab.</p>
    <div class="saved-list">${names.map((name) => {
      const held = saved[name] || {};
      const count = Object.keys(held.shop || {}).length;
      return `<div class="saved-row">
        <div style="flex:1;min-width:0">
          <b class="clip">${esc(name)}</b>
          <div class="muted small">${count} item${count === 1 ? '' : 's'}${
            held.savedAt ? ' &middot; ' + esc(String(held.savedAt).slice(0, 10)) : ''}</div>
        </div>
        <button class="tiny" data-restore="${esc(name)}">Restore</button>
        <button class="ghost tiny danger" data-forget="${esc(name)}">Forget</button>
      </div>`;
    }).join('')}</div></div>`;
}

function wireShop() {
  const save = $('saveList');
  if (save) save.addEventListener('click', async () => {
    const suggested = 'List ' + new Date().toISOString().slice(0, 10);
    const name = (prompt('Name for this list?', suggested) || '').trim();
    if (!name) return;
    const d = state.plan.data;
    const lists = savedLists();
    if (lists[name] && !confirm(`Replace the saved list called "${name}"?`)) return;
    // A deep copy, or restoring it later would hand back whatever the live
    // list had become in the meantime.
    lists[name] = {
      savedAt: new Date().toISOString(),
      shop: JSON.parse(JSON.stringify(d.shop || {})),
      prices: JSON.parse(JSON.stringify(d.prices || {})),
    };
    try {
      await savePlan();
      toast(`Saved as "${name}".`);
      render();
    } catch (err) { toast(err.message); }
  });

  const wipe = $('clearList');
  if (wipe) wipe.addEventListener('click', async () => {
    const count = Object.keys(state.plan.data.shop || {}).length;
    if (!confirm(`Clear all ${count} items from the shopping list?\n\n`
      + 'Recorded prices are kept, and Undo on the Data tab puts it back.')) return;
    state.plan.data.shop = {};
    state.plan.data.got = [];
    try {
      await savePlan();
      toast('List cleared. Undo is on the Data tab.');
      render();
    } catch (err) { toast(err.message); }
  });

  document.querySelectorAll('[data-restore]').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const name = btn.dataset.restore;
      const held = savedLists()[name];
      if (!held) return;
      if (!confirm(`Replace the current list with "${name}"?`)) return;
      const d = state.plan.data;
      d.shop = JSON.parse(JSON.stringify(held.shop || {}));
      // Merge the prices rather than replace them: a price recorded since is
      // newer than the one saved with the list, and history is worth keeping.
      const prices = d.prices || {};
      Object.entries(held.prices || {}).forEach(([food, history]) => {
        if (!prices[food]) prices[food] = history;
      });
      d.prices = prices;
      d.got = [];
      try {
        await savePlan();
        toast(`Restored "${name}".`);
        render();
      } catch (err) { toast(err.message); }
    });
  });

  document.querySelectorAll('[data-forget]').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const name = btn.dataset.forget;
      if (!confirm(`Forget the saved list "${name}"?`)) return;
      delete savedLists()[name];
      try {
        await savePlan();
        render();
      } catch (err) { toast(err.message); }
    });
  });

  document.querySelectorAll('[data-got]').forEach((box) => {
    box.addEventListener('change', async () => {
      const food = box.dataset.got;
      const got = gotSet();
      if (box.checked) got.add(food); else got.delete(food);
      state.plan.data.got = [...got];
      // Repaint the row and the count first; the save follows.
      const row = box.closest('tr');
      if (row) row.classList.toggle('got', box.checked);
      // By id, not by `.card .sub`. The sign-in card stays in the document
      // after you sign in, so the first `.card .sub` on the page is its
      // subtitle -- the count was being written into a hidden element while
      // the real one sat at "0 of 17" however many things you ticked.
      const head = $('basketCount');
      if (head) head.textContent =
        `${got.size} of ${Object.keys(state.plan.data.shop || {}).length} in the basket`;
      // The number that actually matters while standing in an aisle. It used
      // to only recompute on the next full reload -- frozen at exactly the
      // moment it was being watched.
      const totals = shopTotals(state.plan.data.shop || {}, got);
      const totalV = $('shopTotalV');
      if (totalV) totalV.textContent = money(totals.total);
      const remainingV = $('shopRemainingV');
      if (remainingV) remainingV.textContent = money(totals.remaining);
      try {
        await savePlan();
      } catch (err) {
        toast('That tick did not save: ' + err.message);
      }
    });
  });

  document.querySelectorAll('[data-swap]').forEach((b) => {
    b.addEventListener('click', () => openSwap(b.dataset.swap));
  });

  document.querySelectorAll('[data-drop]').forEach((b) => {
    b.addEventListener('click', async () => {
      const food = b.dataset.drop;
      if (!window.confirm(`Take "${food}" off the shopping list?`)) return;
      await api('/plans/' + state.planId + '/shop-items/'
        + encodeURIComponent(food), { method: 'DELETE' });
      await loadPlan();
      render();
    });
  });

  const clear = $('clearGot');
  if (clear) {
    clear.addEventListener('click', async () => {
      state.plan.data.got = [];
      await savePlan();
      render();
    });
  }

  document.querySelectorAll('[data-edit]').forEach((b) => {
    b.addEventListener('click', async () => {
      const food = b.dataset.edit;
      const current = latestPrice(food) || {};
      const priceIn = window.prompt(
        `Price you actually paid for ${food}:`,
        current.price != null ? String(current.price) : '');
      if (priceIn === null) return;
      const price = Number(priceIn);
      if (!(price > 0)) { window.alert('That is not a price.'); return; }
      const packIn = window.prompt(
        'Pack size in grams (blank to keep what is recorded):',
        current.pack != null ? String(current.pack) : '');
      const pack = packIn === null || packIn.trim() === ''
        ? (current.pack || null) : Number(packIn);

      await api('/prices/manual', { method: 'POST',
        body: { food, price, pack: pack || null, store: 'entered by hand' } });

      const list = (state.plan.data.prices = state.plan.data.prices || {});
      (list[food] = list[food] || []).push({
        price, pack: pack || null, date: new Date().toISOString().slice(0, 10),
        store: 'entered by hand', source: 'manual',
      });
      await savePlan();
      render();
    });
  });

  const btn = $('refreshBtn');
  if (!btn) return;
  btn.addEventListener('click', async () => {
    btn.disabled = true;
    btn.textContent = 'Checking prices…';
    $('refreshOut').innerHTML =
      '<div class="note">Checking both stores for every item — this takes a moment.</div>';
    try {
      const res = await api('/plans/' + state.planId + '/refresh-prices',
        { method: 'POST', body: { store: 'Woolworths (online)' } });
      await loadPlan();
      render();
      const out = $('refreshOut');
      if (out) out.innerHTML = refreshSummary(res);
    } catch (err) {
      $('refreshOut').innerHTML = `<div class="err">${esc(err.message)}</div>`;
      btn.disabled = false;
      btn.textContent = 'Refresh prices';
    }
  });
}

/* ------------------------------------------------------------- price history */

// A sparkline drawn as inline SVG. No chart library, so nothing to load and
// nothing to break the artifact-style CSP.
function sparkline(points, width, height) {
  const w = width || 220;
  const h = height || 44;
  if (!points || points.length < 2) return '';
  const values = points.map((p) => p.v);
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  const span = (hi - lo) || 1;
  const pad = 4;
  const x = (i) => pad + (i / (points.length - 1)) * (w - pad * 2);
  const y = (v) => h - pad - ((v - lo) / span) * (h - pad * 2);

  const line = points.map((p, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(p.v).toFixed(1)}`).join('');
  const area = `${line}L${x(points.length - 1).toFixed(1)},${h - pad}L${x(0).toFixed(1)},${h - pad}Z`;
  const last = points[points.length - 1];
  const cheapest = points.reduce((a, b) => (b.v < a.v ? b : a), points[0]);

  return `<svg class="spark" viewBox="0 0 ${w} ${h}" width="${w}" height="${h}"
      role="img" aria-label="Price trend, ${points.length} readings">
    <path d="${area}" fill="var(--accent-soft)"></path>
    <path d="${line}" fill="none" stroke="var(--accent)" stroke-width="1.6"
      stroke-linejoin="round" stroke-linecap="round"></path>
    <circle cx="${x(points.indexOf(cheapest)).toFixed(1)}"
      cy="${y(cheapest.v).toFixed(1)}" r="2.6" fill="var(--accent)"></circle>
    <circle cx="${x(points.length - 1).toFixed(1)}" cy="${y(last.v).toFixed(1)}"
      r="3" fill="var(--ink)"></circle>
  </svg>`;
}

// Is today's price actually good? Compare against the readings before it, not
// against the all-time low -- "cheapest ever" is rare and unhelpful, "cheaper
// than usual" is what decides whether to buy this week.
function dealVerdict(points, last) {
  // With one reading there is nothing to compare against -- except the shelf
  // itself, which says outright when a price is a markdown. That covers the
  // first weeks, when the history is too short to say anything.
  if (!points || points.length < 2) {
    if (last && last.wasPrice && last.price && last.wasPrice > last.price) {
      const off = (last.wasPrice - last.price) / last.wasPrice * 100;
      return { label: 'on special', cls: 'ok',
               detail: `${off.toFixed(0)}% off its usual ${money(last.wasPrice)}.`,
               rank: 1 };
    }
    if (last && last.onSpecial) {
      return { label: 'on special', cls: 'ok',
               detail: 'Marked down at the store.', rank: 1 };
    }
    return { label: 'no history yet', cls: '',
             detail: 'Refresh again next week.', rank: 5 };
  }
  const now = points[points.length - 1].v;
  const prior = points.slice(0, -1).map((p) => p.v);
  const lo = Math.min(...prior);
  const hi = Math.max(...prior);
  const mean = prior.reduce((a, b) => a + b, 0) / prior.length;
  const delta = (now - mean) / mean * 100;

  if (now <= lo) {
    return { rank: 0, label: 'cheapest yet', cls: 'ok',
             detail: `Lowest of ${points.length} readings.` };
  }
  if (delta <= -8) {
    return { rank: 1, label: 'good week to buy', cls: 'ok',
             detail: `${Math.abs(delta).toFixed(0)}% below its usual ${money(mean)}/kg.` };
  }
  if (delta >= 8) {
    return { rank: 6, label: 'dearer than usual', cls: 'stop',
             detail: `${delta.toFixed(0)}% above its usual ${money(mean)}/kg.` };
  }
  if (now >= hi) {
    return { rank: 7, label: 'highest yet', cls: 'stop',
             detail: `Dearest of ${points.length} readings.` };
  }
  return { rank: 4, label: 'about normal', cls: '',
           detail: `Usual price is around ${money(mean)}/kg.` };
}

const priceView = { q: '', sort: 'name' };

const PRICE_SORTS = [
  { id: 'name', label: 'Name, A to Z' },
  { id: 'deal', label: 'Best buys first' },
  { id: 'change', label: 'Biggest change' },
  { id: 'dear', label: 'Dearest per kilo' },
  { id: 'cheap', label: 'Cheapest per kilo' },
  { id: 'readings', label: 'Most readings' },
];

const swap = { food: '', busy: false, items: [], q: '', live: false };

function openSwap(food) {
  swap.food = food;
  swap.items = [];
  swap.q = '';
  swap.live = false;
  const host = document.createElement('div');
  host.id = 'swapHost';
  document.body.appendChild(host);
  drawSwap();
  loadSwap();
}

function closeSwap() {
  const host = $('swapHost');
  if (host) host.remove();
}

function drawSwap() {
  const host = $('swapHost');
  if (!host) return;
  const meta = (state.plan.data.shop || {})[swap.food] || {};
  const now = latestPrice(swap.food);

  host.innerHTML = `<div class="sheet-back" id="swapBack"></div>
    <div class="sheet" role="dialog" aria-label="Choose a product">
      <div class="sheet-top">
        <div style="flex:1;min-width:0">
          <h3 style="margin:0">${esc(shortFood(swap.food))}</h3>
          <p class="muted small" style="margin:3px 0 0">Currently ${now && now.matched
            ? `<b>${esc(now.matched)}</b> at ${money(now.price)}`
            : 'not matched to a product'}</p>
        </div>
        <button class="ghost" id="swapClose">Close</button>
      </div>
      <div class="row">
        <input id="swapFind" type="search" value="${esc(swap.q)}"
          placeholder="search for something else" style="flex:1"
          autocomplete="off">
        <button class="ghost" id="swapLive" title="Ask the store for anything
the catalogue has not seen">Search the store</button>
      </div>
      <div class="sheet-body" style="margin-top:12px">
        ${swap.busy ? '<div class="note">Looking&hellip;</div>' : ''}
        ${!swap.busy && !swap.items.length
          ? '<p class="muted">Nothing found. Try searching the store.</p>' : ''}
        <div class="pick-list">${swap.items.map(swapRow).join('')}</div>
      </div>
    </div>`;

  $('swapBack').addEventListener('click', closeSwap);
  $('swapClose').addEventListener('click', closeSwap);
  const live = $('swapLive');
  if (live) live.addEventListener('click', () => { swap.live = true; loadSwap(); });
  const find = $('swapFind');
  if (find) {
    find.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') { swap.q = find.value; swap.live = false; loadSwap(); }
    });
    if (swap.q) { find.focus(); find.setSelectionRange(swap.q.length, swap.q.length); }
  }
  host.querySelectorAll('[data-take]').forEach((b) => {
    b.addEventListener('click', () => takeSwap(Number(b.dataset.take)));
  });
}

function swapRow(p, i) {
  // The pack size and the flags; the ticket beside it carries the price, the
  // per-kilo and whether it has moved, so none of those are said twice.
  return `<button class="pick" data-take="${i}">
    ${thumb(p)}
    <span class="pick-body">
      <b>${esc(p.name)}</b>
      <span class="muted small">${[packNote(p), ...(p.flags || [])]
        .filter(Boolean).map(esc).join(' &middot; ')}</span>
    </span>
    <span class="pick-meta">${shelfTicket(ticketFrom(p), p.per_kg)}</span>
  </button>`;
}

async function loadSwap() {
  swap.busy = true;
  drawSwap();
  const meta = (state.plan.data.shop || {})[swap.food] || {};
  try {
    const res = await api('/alternatives?food=' + encodeURIComponent(swap.food)
      + '&query=' + encodeURIComponent(swap.q || meta.woo || swap.food)
      + (meta.pack ? '&pack=' + encodeURIComponent(meta.pack) : '')
      + (swap.live ? '&live=true' : ''));
    swap.items = res.products || [];
  } catch (err) {
    swap.items = [];
    toast(err.message);
  }
  swap.busy = false;
  drawSwap();
}

async function takeSwap(index) {
  const p = swap.items[index];
  if (!p) return;
  const d = state.plan.data;
  const shop = d.shop || (d.shop = {});
  const line = shop[swap.food] || (shop[swap.food] = { aisle: 'pantry' });

  // The pack size moves with the product, so the packs needed have to be
  // worked out again -- keeping the old count would price the new tin by the
  // old tin's arithmetic.
  if (p.pack_g) {
    line.pack = p.pack_g;
    if (line.grams) line.packsNeeded = Math.max(1, Math.ceil(line.grams / p.pack_g));
  }
  if (p.image) line.image = p.image;
  if (p.url) line.url = p.url;
  line.stockcode = String(p.stockcode || '');
  // Remember the choice, so a later refresh does not quietly undo it.
  line.pinned = p.name;

  const prices = d.prices || (d.prices = {});
  const history = prices[swap.food] || (prices[swap.food] = []);
  const today = new Date().toISOString().slice(0, 10);
  const record = {
    price: p.pack_price, pack: p.pack_g || line.pack || null, date: today,
    store: p.store || 'Woolworths (online)', source: 'chosen by hand',
    matched: p.name, url: p.url || '',
  };
  if (p.on_special) record.onSpecial = true;
  if (p.was_price) record.wasPrice = p.was_price;
  if (history.length && history[history.length - 1].date === today) {
    history[history.length - 1] = record;
  } else {
    history.push(record);
  }

  closeSwap();
  try {
    await savePlan();
    toast(`Swapped to ${p.name}.`);
  } catch (err) {
    toast(err.message);
  }
  render();
}


function viewPrices() {
  const prices = state.plan.data.prices || {};
  const all = Object.entries(prices).filter(([, h]) => h && h.length);
  if (!all.length) {
    return `<div class="card"><h2>No prices yet</h2>
      <p class="sub">Use &ldquo;Refresh prices&rdquo; on the shopping list.
        Each refresh adds a reading, and the trend appears once there are two.</p></div>`;
  }

  // Everything a row needs, worked out once so the sort can use it too.
  const rows = all.map(([food, history]) => {
    const points = history.map((e) => ({ v: perKg(e), d: e.date }))
      .filter((p) => p.v);
    const last = history[history.length - 1];
    const now = points.length ? points[points.length - 1].v : null;
    const before = points.length > 1 ? points[points.length - 2].v : null;
    const change = (now && before) ? (now - before) / before : 0;
    return { food, history, points, last, now, before, change,
             verdict: dealVerdict(points, last) };
  });

  const needle = priceView.q.trim().toLowerCase();
  const shown = needle
    ? rows.filter((r) => r.food.toLowerCase().includes(needle)
        || String(r.last.matched || '').toLowerCase().includes(needle)
        || String(r.last.store || '').toLowerCase().includes(needle))
    : rows.slice();

  const byName = (a, b) => a.food.localeCompare(b.food, undefined,
    { sensitivity: 'base' });
  const sorters = {
    // Alphabetical by default. A price list is something you look a thing up
    // in, and a list in whatever order it was written is not lookupable.
    name: byName,
    deal: (a, b) => (a.verdict.rank - b.verdict.rank) || byName(a, b),
    change: (a, b) => Math.abs(b.change) - Math.abs(a.change) || byName(a, b),
    dear: (a, b) => (b.now || 0) - (a.now || 0) || byName(a, b),
    cheap: (a, b) => (a.now || Infinity) - (b.now || Infinity) || byName(a, b),
    readings: (a, b) => b.points.length - a.points.length || byName(a, b),
  };
  shown.sort(sorters[priceView.sort] || byName);

  const body = shown.map((r) => `<tr>
      <td><b>${esc(r.food)}</b>
        <div class="muted small">${esc(r.last.matched || r.last.store || '')}
          ${r.last.source === 'manual' ? '<span class="tag">by hand</span>' : ''}</div></td>
      <td class="r" data-label="Now">${shelfTicket(r.last, r.now)}</td>
      ${deltaCell(r.now, r.before)}
      <td class="spark-cell">${sparkline(r.points)}</td>
      <td data-label="Verdict"><span class="tag ${r.verdict.cls}">${
        esc(r.verdict.label)}</span>
        <div class="muted small">${esc(r.verdict.detail)}</div></td>
      <td class="r muted num small" data-label="Readings">${r.points.length}</td>
    </tr>`).join('');

  const good = rows.filter((r) => r.verdict.rank <= 1).length;

  return `<div class="card">
    <div class="row" style="align-items:baseline">
      <div style="flex:1;min-width:0">
        <h2 style="margin:0">Prices over time</h2>
        <p class="sub" style="margin:4px 0 0">${all.length} foods tracked${
          good ? `, <b>${good}</b> worth buying this week` : ''}.
          The dot on the line is the cheapest reading; the dark dot is now.</p>
        ${autoPriceLine()}
      </div>
    </div>
    <div class="row" style="margin:14px 0 4px">
      <div style="flex:2;min-width:170px">
        <label for="priceFind">Find a food</label>
        <input id="priceFind" type="search" placeholder="type to filter"
          value="${esc(priceView.q)}" autocomplete="off"></div>
      <div style="flex:1;min-width:150px">
        <label for="priceSort">Order</label>
        <select id="priceSort">${optionsFor(PRICE_SORTS, priceView.sort)}</select></div>
    </div>
    <p class="muted small" style="margin:0 0 10px">${
      needle ? `${shown.length} of ${all.length} shown.` : ''}</p>
    ${shown.length ? `<div class="scroll"><table>
      <thead><tr><th>Food</th><th class="r">Now</th><th class="r">Change</th>
        <th>Trend</th><th>Verdict</th><th class="r">Readings</th></tr></thead>
      <tbody>${body}</tbody></table></div>`
      : `<p class="muted">Nothing matches &ldquo;${esc(priceView.q)}&rdquo;.</p>`}
    </div>`;
}

// Both supermarkets change their specials over on a Wednesday, so that is the
// day the readings are taken. Saying so here answers the obvious question --
// whether any of this happens without pressing a button.
function autoPriceLine() {
  const a = state.autoPrice;
  if (!a || !a.enabled) {
    return `<p class="muted small" style="margin:6px 0 0">Prices only change
      when you press <b>Refresh prices</b> on the shopping list.</p>`;
  }
  const when = a.nextRunInHours != null
    ? (a.nextRunInHours < 24
        ? `in about ${Math.round(a.nextRunInHours)} hours`
        : `in about ${Math.round(a.nextRunInHours / 24)} days`)
    : 'soon';
  return `<p class="muted small" style="margin:6px 0 0">Checked automatically
    every ${esc(a.day)} at ${String(a.hour).padStart(2, '0')}:00, when both
    supermarkets change their specials over &mdash; next ${esc(when)}.
    <button class="ghost tiny" id="priceNow">Check now</button></p>`;
}


function wirePrices() {
  const now = $('priceNow');
  if (now) now.addEventListener('click', async () => {
    now.disabled = true;
    now.textContent = 'Checking…';
    try {
      const res = await api('/auto-price/run', { method: 'POST' });
      await loadPlan();
      toast(res.lines
        ? `Took ${res.lines} new reading${res.lines === 1 ? '' : 's'}.`
        : 'Everything was priced recently enough already.');
    } catch (err) {
      toast(err.message);
    }
    render();
  });

  const find = $('priceFind');
  if (find) {
    find.addEventListener('input', () => {
      priceView.q = find.value;
      render();
      // Repainting replaces the field, so put the cursor back where it was.
      const again = $('priceFind');
      if (again) { again.focus(); again.setSelectionRange(again.value.length,
        again.value.length); }
    });
  }
  const sort = $('priceSort');
  if (sort) sort.addEventListener('change', () => {
    priceView.sort = sort.value;
    render();
  });
}


/* -------------------------------------------------------------- data i/o */

// Accepts a plan .html (pulls the state block out of it), a .json export, or
// pasted text -- so nobody has to open a file in Notepad and copy it across.
function extractPlanState(text) {
  const trimmed = (text || '').trim();
  if (!trimmed) throw new Error('That file is empty.');

  if (trimmed.startsWith('{')) return JSON.parse(trimmed);

  const m = trimmed.match(
    /<script[^>]*id=["']state["'][^>]*>([\s\S]*?)<\/script>/i);
  if (m) return JSON.parse(m[1].replace(/<\\\//g, '</'));

  // Last resort: the largest {...} block in the file.
  const first = trimmed.indexOf('{');
  const last = trimmed.lastIndexOf('}');
  if (first !== -1 && last > first) return JSON.parse(trimmed.slice(first, last + 1));

  throw new Error('No plan data found in that file.');
}

function summarisePlan(d) {
  const bits = [];
  const n = (o) => (Array.isArray(o) ? o.length : Object.keys(o || {}).length);
  if (n(d.shop)) bits.push(`${n(d.shop)} shopping items`);
  if (n(d.prices)) bits.push(`${n(d.prices)} priced foods`);
  if (n(d.recipes)) bits.push(`${n(d.recipes)} recipes`);
  if (n(d.foods)) bits.push(`${n(d.foods)} foods with nutrition`);
  if (n(d.days)) bits.push(`${n(d.days)} days`);
  return bits.length ? bits.join(', ') : 'no recognisable plan sections';
}

function viewData() {
  return `<div class="card">
    <h2>Import a plan</h2>
    <p class="sub">Drop a plan file here, choose one, or paste its contents.
      A <code>.html</code> plan works as-is &mdash; no need to dig the JSON out first.</p>
    <div id="drop" class="dropzone">
      <p><b>Drop a .html or .json plan here</b></p>
      <p class="muted small">or</p>
      <input type="file" id="importFile" accept=".html,.htm,.json,application/json,text/html">
    </div>
    <details style="margin-top:12px"><summary class="muted small">Paste it instead</summary>
      <textarea id="importText" rows="6" style="margin-top:8px"
        placeholder='{"meta":…,"shop":…}'></textarea>
      <button id="importPaste" style="margin-top:8px">Import pasted text</button>
    </details>
    <div id="importOut" style="margin-top:12px"></div>
  </div>

  <div class="card">
    <h2>Export</h2>
    <p class="sub">Everything in this plan, as JSON you can re-import anywhere.</p>
    <div class="row">
      <button id="exportGo">Download this plan</button>
      <button id="exportRecipes" class="ghost">Download recipe library</button>
    </div>
  </div>

  <div class="card">
    <h2>Danger zone</h2>
    <p class="sub">Clears the week, the shopping list and the tick marks in this
      plan. Your recipe library and price history are untouched.</p>
    <button id="resetPlan" class="danger">Reset this plan</button>
  </div>`;
}

async function applyImport(text) {
  const out = $('importOut');
  try {
    const parsed = extractPlanState(text);
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
      throw new Error('That is not a plan object.');
    }
    // Keep anything the imported file did not mention, rather than wiping it.
    state.plan.data = { ...state.plan.data, ...parsed };
    await savePlan();
    await loadPlan();
    out.className = 'note';
    out.innerHTML = `Imported ${esc(summarisePlan(parsed))}.
      ${(parsed.days || []).length && !(parsed.week || []).length
        ? 'This plan uses the older <code>days</code> format &mdash; the Week tab'
          + ' builds its own schedule from your recipe library.'
        : ''}`;
    render();
  } catch (err) {
    out.className = 'err';
    out.textContent = err.message;
  }
}

function wireData() {
  const file = $('importFile');
  if (file) {
    file.addEventListener('change', async () => {
      const f = file.files && file.files[0];
      if (f) applyImport(await f.text());
    });
  }

  const drop = $('drop');
  if (drop) {
    ['dragenter', 'dragover'].forEach((e) => drop.addEventListener(e, (ev) => {
      ev.preventDefault();
      drop.classList.add('over');
    }));
    ['dragleave', 'drop'].forEach((e) => drop.addEventListener(e, (ev) => {
      ev.preventDefault();
      drop.classList.remove('over');
    }));
    drop.addEventListener('drop', async (ev) => {
      const f = ev.dataTransfer && ev.dataTransfer.files && ev.dataTransfer.files[0];
      if (f) applyImport(await f.text());
    });
  }

  const paste = $('importPaste');
  if (paste) {
    paste.addEventListener('click', () => applyImport($('importText').value));
  }

  const save = (name, payload) => {
    const blob = new Blob([JSON.stringify(payload, null, 2)],
      { type: 'application/json' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = name;
    a.click();
    URL.revokeObjectURL(a.href);
  };

  const exportGo = $('exportGo');
  if (exportGo) {
    exportGo.addEventListener('click', () => save(
      (state.plan.name || 'plan').replace(/\W+/g, '-').toLowerCase() + '.json',
      state.plan.data));
  }
  const exportRecipes = $('exportRecipes');
  if (exportRecipes) {
    exportRecipes.addEventListener('click', () =>
      save('recipe-library.json', state.recipes || []));
  }

  const reset = $('resetPlan');
  if (reset) {
    reset.addEventListener('click', async () => {
      if (!window.confirm('Clear the week, shopping list and ticks in this plan?')) return;
      const keep = state.plan.data.prices || {};
      state.plan.data = { ...state.plan.data, week: [], shop: {}, got: [], prices: keep };
      await savePlan();
      await loadPlan();
      render();
    });
  }
}

/* ------------------------------------------------------------- find food */

const find = { mode: 'catalogue', q: '', store: '', sort: 'relevance',
               special: false, offset: 0, last: null, stats: null };

function viewSearch() {
  const s = find.stats;
  const counts = s && s.total
    ? `${s.total.toLocaleString()} products indexed`
      + (s.onSpecial ? ` &middot; ${s.onSpecial} on special` : '')
      + ' &middot; ' + Object.entries(s.byStore)
          .map(([k, v]) => `${esc(k)} ${v.toLocaleString()}`).join(', ')
    : 'Nothing indexed yet — search the stores below and it fills up as you go.';

  return `<div class="card">
    <h2>Find food</h2>
    <p class="sub">${counts}</p>

    <div class="row" style="margin-bottom:10px">
      <div class="seg">
        <button class="${find.mode === 'catalogue' ? 'on' : ''}" data-mode="catalogue">Indexed</button>
        <button class="${find.mode === 'live' ? 'on' : ''}" data-mode="live">Search the stores</button>
      </div>
    </div>

    <div class="row">
      <input id="q" placeholder="${find.mode === 'catalogue'
        ? 'e.g. greek yoghurt' : 'e.g. rolled oats'}" value="${esc(find.q)}"
        style="flex:1;min-width:180px">
      <button id="goSearch" class="primary">Search</button>
      ${scanButton()}
    </div>
    ${scannerSupported() ? '' : `<p class="muted small" style="margin:8px 0 0">
      Barcode scanning needs Chrome on Android; this browser has no scanner.</p>`}

    <div class="row" style="margin-top:10px">
      <select id="fStore" style="width:auto">
        <option value="">Both stores</option>
        <option value="woolworths"${find.store === 'woolworths' ? ' selected' : ''}>Woolworths</option>
        <option value="coles"${find.store === 'coles' ? ' selected' : ''}>Coles</option>
      </select>
      ${find.mode === 'catalogue' ? `
      <select id="fSort" style="width:auto">
        <option value="relevance"${find.sort === 'relevance' ? ' selected' : ''}>Best match</option>
        <option value="cheapest"${find.sort === 'cheapest' ? ' selected' : ''}>Cheapest per kg</option>
        <option value="dearest"${find.sort === 'dearest' ? ' selected' : ''}>Dearest per kg</option>
        <option value="name"${find.sort === 'name' ? ' selected' : ''}>Name</option>
      </select>
      <label class="tick" style="font-size:14px">
        <input type="checkbox" id="fSpecial"${find.special ? ' checked' : ''}>
        <span>On special only</span></label>` : ''}
    </div>

    <p class="muted small" style="margin:10px 0 0">${find.mode === 'catalogue'
      ? 'Searches what this server has already seen. Instant, and works even when a store is blocking us.'
      : 'Asks Woolworths and Coles directly. Slower, and anything it finds is added to the index.'}</p>

    <div id="searchOut" style="margin-top:14px"></div>
  </div>`;
}

function thumb(p) {
  // Deliberately not lazy. It was, on the reasoning that a catalogue page can
  // hold sixty of these and the store CDNs are slow -- but inside these
  // scrolling panels Chrome never decides they are near enough to load, so
  // every thumbnail sat for ever at an empty currentSrc. A picture that never
  // arrives is worth less than a slow one.
  //
  // A glyph rather than a letter, here as everywhere else, and it is what a
  // broken store URL falls back to -- the common case for an image the
  // catalogue recorded months ago.
  const mark = foodGlyph(p.name)
    || esc((p.name || '?').trim().charAt(0).toUpperCase());
  if (!p.image) {
    return `<div class="thumb none" aria-hidden="true">${mark}</div>`;
  }
  return `<img class="thumb" src="${esc(p.image)}" alt=""
    decoding="async" referrerpolicy="no-referrer"
    data-onfail="glyph" data-fail-class="thumb none"
    data-fail-mark="${esc(mark)}">`;
}

function resultRows(items) {
  return items.map((p, i) => {
    const key = `${p.store}:${p.stockcode}`;
    const link = p.url
      ? ` <a href="${esc(p.url)}" target="_blank" rel="noopener noreferrer" title="Open at the store">&#8599;</a>`
      : '';
    return `<tr>
      <td class="prod"><div class="prod-row">${thumb(p)}<div>
        <b>${esc(p.name)}</b>${
          p.in_stock === false ? ' <span class="tag stop">out of stock</span>' : ''}${link}
        <div class="muted small">${esc(packNote(p))}</div></div></div></td>
      <td data-label="Store"><span class="tag">${esc(p.store)}</span></td>
      <td class="r" data-label="Price">${
        shelfTicket(ticketFrom(p), p.per_kg)}</td>
      <td class="r"><button class="tiny" data-add-prod="${esc(key)}"
        data-idx="${i}">Add to list</button></td>
    </tr>`;
  }).join('');
}

function resultTable(items, note) {
  if (!items.length) {
    return `<div class="note">Nothing found. ${note || ''}</div>`;
  }
  return `${note ? `<div class="row" style="margin-bottom:10px">${note}</div>` : ''}
    <div class="scroll"><table><thead><tr>
      <th>Product</th><th>Store</th><th class="r">Price</th><th></th>
    </tr></thead><tbody>${resultRows(items)}</tbody></table></div>`;
}

async function runFind() {
  const out = $('searchOut');
  find.q = $('q').value.trim();
  out.innerHTML = '<div class="note">Searching…</div>';
  try {
    if (find.mode === 'catalogue') {
      const params = new URLSearchParams({
        q: find.q, sort: find.sort, limit: '60', offset: String(find.offset),
      });
      if (find.store) params.set('store', find.store);
      if (find.special) params.set('on_special', 'true');
      const res = await api('/catalogue?' + params);
      find.last = res.products;
      const shown = res.products.length;
      const note = `<span class="muted small">${res.total.toLocaleString()} match${
        res.total === 1 ? '' : 'es'}${shown < res.total ? `, showing ${shown}` : ''}</span>`;
      out.innerHTML = resultTable(res.products,
        res.total ? note : 'Try <b>Search the stores</b> instead — it will index what it finds.');
    } else {
      const params = new URLSearchParams({ q: find.q, limit: '36' });
      if (find.store) params.set('store', find.store);
      const res = await api('/search?' + params);
      find.last = res.products;
      const freshness = Object.entries(res.byStore || {}).map(([store, v]) => {
        if (v.status !== 'success') return `<span class="tag stop">${esc(store)}: unavailable</span>`;
        if (v.stale) return `<span class="tag warn">${esc(store)}: ${describeAge(v.ageHours)}</span>`;
        if (v.cached) return `<span class="tag">${esc(store)}: checked ${describeAge(v.ageHours)}</span>`;
        return `<span class="tag ok">${esc(store)}: just checked</span>`;
      }).join(' ');
      out.innerHTML = resultTable(res.products, freshness);
    }
    wireAddButtons();
  } catch (err) {
    out.innerHTML = `<div class="err">${esc(err.message)}</div>`;
  }
}

function wireAddButtons() {
  document.querySelectorAll('[data-add-prod]').forEach((b) => {
    b.addEventListener('click', async () => {
      const p = (find.last || [])[Number(b.dataset.idx)];
      if (!p) return;
      b.disabled = true;
      b.textContent = 'Adding…';
      try {
        const aisle = window.prompt(
          `Which part of the shop is "${p.name}" in?\n\nproduce, meat, fridge, pantry or freezer`,
          guessAisle(p.name)) || 'other';
        const res = await api('/plans/' + state.planId + '/shop-items', {
          method: 'POST',
          body: { store: p.store, stockcode: String(p.stockcode),
                  aisle: aisle.trim().toLowerCase() },
        });
        await loadPlan();
        b.textContent = 'On list';
        b.classList.add('done');
      } catch (err) {
        b.disabled = false;
        b.textContent = 'Add';
        const box = $('searchOut');
        const msg = document.createElement('div');
        msg.className = 'err';
        msg.style.marginTop = '10px';
        msg.textContent = err.message;
        box.appendChild(msg);
        setTimeout(() => msg.remove(), 5000);
      }
    });
  });
}

// A first guess so the prompt is usually just an Enter press.
// A recipe site writes the ingredient list for a cook, not a shopping list.
// "225g / 7oz chicken thigh fillets (, skinless boneless, cut into bite size
// pieces)" says how to prepare it as much as what it is -- and the alternate
// measure ("/ 7oz") is left stuck to the front once the first unit is used,
// which is why the app's own matching (and its shopping list) needs this and
// the parser upstream does not do it for us.
function cleanIngredientName(part) {
  let name = (part.item || part.original || '').trim();
  name = name.replace(/^\/\s*[\d.]+\s*(?:fl\s?oz|floz|oz|lbs?|g|kg|ml|l)\.?\s*/i, '');
  // Run twice: "(, packed (Holy Basil, if you can find it) (Note 1))" nests,
  // and a single pass only clears the innermost pair.
  for (let i = 0; i < 3; i++) name = name.replace(/\([^()]*\)/g, ' ');
  name = name.replace(/,.*$/, '');
  name = name.replace(/^[\s,\/]+|[\s,\/]+$/g, '').replace(/\s+/g, ' ').trim();
  return name || (part.original || '').trim();
}

// Nutrition for every distinct ingredient an imported recipe names, matched
// once and cached rather than guessed at again on every render.
async function loadImportEstimates(r) {
  const names = [...new Set((r.ingredients || []).map(cleanIngredientName))]
    .filter(Boolean);
  if (!names.length) { found.nutrition = {}; return; }
  try {
    const res = await api('/nutrition/estimate-many',
      { method: 'POST', body: { names } });
    found.nutrition = res.results || {};
  } catch (err) {
    found.nutrition = {};
  }
}

// The rows a saved recipe actually needs -- one per ingredient, in the same
// shape a generated or hand-written recipe already carries, so the planner,
// the day totals and the shopping list treat an import no differently.
function importedRows(r) {
  const grams = r.scaledGrams || [];
  return (r.ingredients || []).map((part, i) => {
    const food = cleanIngredientName(part);
    const total = grams[i];
    const per = (r.servings && total != null) ? total / r.servings : null;
    const est = found.nutrition[food];
    return {
      food, gramsPerServing: per, gramsTotal: total,
      query: food, pack: null, aisle: guessAisle(food), role: 'other',
      image: '', per100: (est && est.status === 'ok') ? est.per100 : null,
    };
  });
}

function importedTotals(rows) {
  const t = { kcal: 0, p: 0, c: 0, f: 0, fb: 0 };
  let known = 0;
  rows.forEach((i) => {
    if (!i.per100 || i.gramsPerServing == null) return;
    known += 1;
    const factor = i.gramsPerServing / 100;
    ['kcal', 'p', 'c', 'f', 'fb'].forEach((k) => { t[k] += (i.per100[k] || 0) * factor; });
  });
  return { perServing: t, known, unknown: rows.length - known };
}


function guessAisle(name) {
  const n = (name || '').toLowerCase();
  if (/frozen|ice cream/.test(n)) return 'freezer';
  if (/chicken|beef|pork|lamb|mince|steak|sausage|bacon|salmon|tuna|prawn|fish/.test(n)) return 'meat';
  if (/milk|yoghurt|cheese|butter|cream|egg|tofu/.test(n)) return 'fridge';
  if (/apple|banana|orange|lemon|potato|carrot|onion|tomato|broccoli|spinach|lettuce|cucumber|avocado|berry|berries|grape|capsicum|zucchini|mushroom|pumpkin/.test(n)) return 'produce';
  return 'pantry';
}

function wireSearch() {
  const scanOpen = $('scanOpen');
  if (scanOpen) scanOpen.addEventListener('click', openScanner);

  document.querySelectorAll('[data-mode]').forEach((b) => {
    b.addEventListener('click', () => {
      find.mode = b.dataset.mode;
      find.offset = 0;
      render();
    });
  });
  const go = $('goSearch');
  if (go) go.addEventListener('click', () => { find.offset = 0; runFind(); });
  const q = $('q');
  if (q) {
    q.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') { find.offset = 0; runFind(); }
    });
    q.focus();
    q.selectionStart = q.value.length;
  }
  const st = $('fStore');
  if (st) st.addEventListener('change', () => { find.store = st.value; runFind(); });
  const so = $('fSort');
  if (so) so.addEventListener('change', () => { find.sort = so.value; runFind(); });
  const sp = $('fSpecial');
  if (sp) sp.addEventListener('change', () => { find.special = sp.checked; runFind(); });

  loadCatalogueStats();
}

async function loadCatalogueStats() {
  try {
    const s = await api('/catalogue/stats');
    if (JSON.stringify(s) !== JSON.stringify(find.stats)) {
      find.stats = s;
      const sub = document.querySelector('#panels .card .sub');
      if (sub && s.total) {
        sub.innerHTML = `${s.total.toLocaleString()} products indexed`
          + (s.onSpecial ? ` &middot; ${s.onSpecial} on special` : '')
          + ' &middot; ' + Object.entries(s.byStore)
              .map(([k, v]) => `${esc(k)} ${v.toLocaleString()}`).join(', ');
      }
    }
  } catch (_) { /* not fatal */ }
}


/* ------------------------------------------------------------ week plan */


// A recipe earns its place in Favourites by being rated well or cooked more
// than once -- which is what the "Cooked it" counter is for.
function isFavourite(r) {
  return (r.rating || 0) >= 4 || (r.timesCooked || 0) >= 2;
}

function categoryOf(r) {
  return CAT_ORDER.includes(r.category) ? r.category : 'other';
}

// Monday of the current week, so the days can carry real dates.
function mondayOf(date) {
  const d = new Date(date);
  d.setHours(0, 0, 0, 0);
  d.setDate(d.getDate() - ((d.getDay() + 6) % 7));
  return d;
}

function dayDate(index) {
  const base = week.monday ? new Date(week.monday) : mondayOf(new Date());
  base.setDate(base.getDate() + index);
  return base;
}

function shortDate(d) {
  return d.toLocaleDateString(undefined, { day: 'numeric', month: 'short' });
}

function isToday(d) {
  const now = new Date();
  return d.toDateString() === now.toDateString();
}


/* ---- the picker ---- */

function pickerHtml(dayIndex) {
  const library = state.recipes || [];
  const favourites = library.filter(isFavourite);
  const groups = CAT_ORDER
    .map((cat) => [cat, library.filter((r) => categoryOf(r) === cat)])
    .filter(([, list]) => list.length);

  const card = (r) => `<button class="pick" data-choose="${r.id}">
    <span class="dot cat-${esc(categoryOf(r))}"></span>
    <span class="pick-body">
      <b>${esc(r.name)}</b>
      <span class="muted small">${Math.round((r.perServing || {}).kcal || 0)} kcal
        &middot; ${Math.round((r.perServing || {}).p || 0)}g protein
        &middot; makes ${r.servings || '?'}</span>
    </span>
    <span class="pick-meta">
      ${r.rating ? `<span class="tag warn">${'★'.repeat(r.rating)}</span>` : ''}
      ${r.timesCooked ? `<span class="tag">cooked ${r.timesCooked}&times;</span>` : ''}
    </span></button>`;

  const section = (title, list) => list.length
    ? `<h4 class="pick-head">${esc(title)} <span class="muted">${list.length}</span></h4>
       <div class="pick-list">${list.map(card).join('')}</div>` : '';

  return `<div class="sheet-back" id="sheetBack"></div>
    <div class="sheet" role="dialog" aria-label="Choose a recipe">
      <div class="sheet-top">
        <div><h3 style="margin:0">Add to ${esc(DAYS[dayIndex])}</h3>
          <p class="muted small" style="margin:2px 0 0">${shortDate(dayDate(dayIndex))}</p></div>
        <div class="row">
          <label class="muted small">Servings
            <input type="number" id="pickServ" value="1" min="1" max="10"
              style="width:58px;margin-left:6px"></label>
          <button class="ghost" id="sheetClose">Close</button>
        </div>
      </div>
      <input id="pickFilter" placeholder="Filter by name…" style="margin:0 0 12px">
      <div class="sheet-body" id="sheetBody">
        ${section('Favourites', favourites)}
        ${groups.map(([cat, list]) => section(CAT_LABEL[cat], list)).join('')}
      </div>
    </div>`;
}

// How unlike the meal being replaced a candidate is. Energy and protein are
// what a day is actually built on, so they carry the weight; fibre matters but
// is easier to make up elsewhere.
function mealDistance(a, b) {
  const x = a.perServing || {};
  const y = b.perServing || {};
  return Math.abs((x.kcal || 0) - (y.kcal || 0)) / 100
    + Math.abs((x.p || 0) - (y.p || 0)) / 8
    + Math.abs((x.fb || 0) - (y.fb || 0)) / 12;
}

function openMealSwap(di, mi) {
  const day = weekData()[di];
  const line = (day.meals || [])[mi];
  const current = line && recipeById(line.recipeId);
  if (!line) return;

  const sitting = line.meal || '';
  const alike = (state.recipes || [])
    .filter((r) => r.id !== line.recipeId)
    .filter((r) => !sitting || weekSuits(r, sitting))
    .map((r) => ({ r, d: current ? mealDistance(current, r) : 0 }))
    .sort((a, b) => a.d - b.d)
    .slice(0, 24);

  const host = document.createElement('div');
  host.id = 'mealSwapHost';
  const per = (current && current.perServing) || {};
  host.innerHTML = `<div class="sheet-back" id="msBack"></div>
    <div class="sheet" role="dialog" aria-label="Swap this meal">
      <div class="sheet-top">
        <div style="flex:1;min-width:0">
          <h3 style="margin:0">Instead of ${esc(
            current ? current.name : 'this meal')}</h3>
          <p class="muted small" style="margin:3px 0 0">${
            Math.round(per.kcal || 0)} kcal &middot; ${
            Math.round(per.p || 0)}g protein &middot; ${
            Math.round(per.fb || 0)}g fibre${sitting ? ` &middot; ${esc(sitting)}` : ''}
            &mdash; closest first.</p>
        </div>
        <button class="ghost" id="msClose">Close</button>
      </div>
      <div class="sheet-body">
        ${alike.length ? `<div class="pick-list">${alike.map(({ r }) => {
          const p = r.perServing || {};
          const dk = Math.round((p.kcal || 0) - (per.kcal || 0));
          const dp = Math.round((p.p || 0) - (per.p || 0));
          const df = Math.round((p.fb || 0) - (per.fb || 0));
          // "same kcal same g P same g F" is three ways of saying one thing.
          const shift = (n, unit) => n === 0 ? ''
            : `<span class="${n > 0 ? 'up' : 'down'}">${n > 0 ? '+' : ''}${n}${unit}</span>`;
          const deltas = [shift(dk, ' kcal'), shift(dp, 'g P'), shift(df, 'g F')]
            .filter(Boolean).join(' ') || '<span class="muted">much the same</span>';
          return `<button class="pick" data-msTake="${r.id}">
            <span class="dot cat-${esc(categoryOf(r))}"></span>
            <span class="pick-body">
              <b>${esc(r.name)}</b>
              <span class="muted small">${Math.round(p.kcal || 0)} kcal &middot;
                ${Math.round(p.p || 0)}g protein &middot;
                ${Math.round(p.fb || 0)}g fibre</span>
            </span>
            <span class="pick-meta small num">${deltas}</span>
          </button>`;
        }).join('')}</div>`
        : `<p class="muted">Nothing else in your library suits ${
            sitting ? esc(sitting) : 'this meal'}. Save a few more from the
            recipe book.</p>`}
      </div>
    </div>`;
  document.body.appendChild(host);

  const shut = () => host.remove();
  $('msBack').addEventListener('click', shut);
  $('msClose').addEventListener('click', shut);
  host.querySelectorAll('[data-mstake]').forEach((b) => {
    b.addEventListener('click', async () => {
      weekData()[di].meals[mi].recipeId = Number(b.dataset.mstake);
      auto.result = null;
      shut();
      try {
        await savePlan();
      } catch (err) {
        toast(err.message);
      }
      render();
    });
  });
}

// The same rule the planner uses, so the sitting a dish belongs to means the
// same thing on both sides.
function weekSuits(r, sitting) {
  if (!sitting) return true;
  const listed = r.meals || (r.meal ? [r.meal] : null);
  return (listed || ['lunch', 'dinner']).includes(sitting);
}


function openPicker(dayIndex) {
  week.picker = dayIndex;
  const host = document.createElement('div');
  host.id = 'pickerHost';
  host.innerHTML = pickerHtml(dayIndex);
  document.body.appendChild(host);

  const close = () => { host.remove(); week.picker = null; };
  $('sheetBack').addEventListener('click', close);
  $('sheetClose').addEventListener('click', close);
  document.addEventListener('keydown', function esc(e) {
    if (e.key === 'Escape') { close(); document.removeEventListener('keydown', esc); }
  });

  const filter = $('pickFilter');
  filter.addEventListener('input', () => {
    const q = filter.value.toLowerCase();
    host.querySelectorAll('.pick').forEach((b) => {
      b.style.display = b.textContent.toLowerCase().includes(q) ? '' : 'none';
    });
    host.querySelectorAll('.pick-head').forEach((h) => {
      const list = h.nextElementSibling;
      const any = [...list.querySelectorAll('.pick')].some((b) => b.style.display !== 'none');
      h.style.display = any ? '' : 'none';
      list.style.display = any ? '' : 'none';
    });
  });
  filter.focus();

  host.querySelectorAll('[data-choose]').forEach((b) => {
    b.addEventListener('click', async () => {
      const servings = Math.max(1, Number($('pickServ').value) || 1);
      weekData()[dayIndex].meals.push({
        recipeId: Number(b.dataset.choose), servings, on: true,
        meal: sittingFor(dayIndex),
      });
      // The planner's report describes the week it planned, not this one.
      auto.result = null;
      close();
      await savePlan();
      render();
    });
  });
}

function wireWeek() {
  document.querySelectorAll('[data-pick]').forEach((b) => {
    b.addEventListener('click', () => openPicker(Number(b.dataset.pick)));
  });

  // Skip a meal without deleting it -- the plan for a day you eat out is not
  // the same as never having planned it.
  document.querySelectorAll('[data-on]').forEach((box) => {
    box.addEventListener('change', async () => {
      const [di, mi] = box.dataset.on.split(':').map(Number);
      weekData()[di].meals[mi].on = box.checked;
      auto.result = null;
      await savePlan();
      render();
    });
  });

  document.querySelectorAll('[data-mult]').forEach((input) => {
    input.addEventListener('change', async () => {
      const [di, mi] = input.dataset.mult.split(':').map(Number);
      weekData()[di].meals[mi].servings =
        Math.max(0.1, Math.round((Number(input.value) || 1) * 10) / 10);
      auto.result = null;
      await savePlan();
      render();
    });
  });

  const saveGoal = async (id, key) => {
    const el = $(id);
    if (!el) return;
    el.addEventListener('change', async () => {
      state.plan.data.meta = state.plan.data.meta || {};
      state.plan.data.meta[key] = Number(el.value) || 0;
      await savePlan();
      render();
    });
  };
  saveGoal('gCeiling', 'ceiling');
  saveGoal('gFloorP', 'floorP');
  saveGoal('gFloorF', 'floorF');

  document.querySelectorAll('[data-mealswap]').forEach((b) => {
    b.addEventListener('click', () => {
      const [di, mi] = b.dataset.mealswap.split(':').map(Number);
      openMealSwap(di, mi);
    });
  });

  document.querySelectorAll('[data-rm]').forEach((b) => {
    b.addEventListener('click', async () => {
      const [di, mi] = b.dataset.rm.split(':').map(Number);
      weekData()[di].meals.splice(mi, 1);
      auto.result = null;
      await savePlan();
      render();
    });
  });

  const shift = (days) => {
    const d = new Date(week.monday);
    d.setDate(d.getDate() + days);
    week.monday = d;
    render();
  };
  const prev = $('weekPrev');
  if (prev) prev.addEventListener('click', () => shift(-7));
  const next = $('weekNext');
  if (next) next.addEventListener('click', () => shift(7));
  const today = $('weekToday');
  if (today) today.addEventListener('click', () => {
    week.monday = mondayOf(new Date());
    render();
  });

  document.querySelectorAll('[data-view]').forEach((b) => {
    b.addEventListener('click', () => {
      week.one = b.dataset.view === 'one';
      if (week.one && week.day == null) week.day = todayIndex();
      try {
        localStorage.setItem('shelfplan.weekOne', week.one ? '1' : '0');
      } catch (_) { /* a private window just forgets the preference */ }
      render();
    });
  });
  const backADay = $('dayPrev');
  if (backADay) backADay.addEventListener('click', () => {
    week.day = (week.day + 6) % 7;
    render();
  });
  const onADay = $('dayNext');
  if (onADay) onADay.addEventListener('click', () => {
    week.day = (week.day + 1) % 7;
    render();
  });

  const detail = $('weekDetail');
  if (detail) detail.addEventListener('click', () => {
    week.detail = !week.detail;
    try {
      localStorage.setItem('shelfplan.weekDetail', week.detail ? '1' : '0');
    } catch (_) { /* a private window just forgets the preference */ }
    render();
  });

  const undo = $('planUndo');
  if (undo) {
    undo.addEventListener('click', async () => {
      try {
        const res = await api('/plans/' + state.planId + '/undo', { method: 'POST' });
        await loadPlan();
        // Same reason as clearing: the report describes a week that has just
        // been replaced by an older one.
        auto.result = null;
        render();
        const out = $('weekOut');
        if (out) {
          out.innerHTML = `<div class="note">Restored the version saved
            ${esc(res.restoredFrom || 'earlier')}. Press Undo again to go back
            further.</div>`;
        }
      } catch (err) {
        const out = $('weekOut');
        if (out) out.innerHTML = `<div class="err">${esc(err.message)}</div>`;
      }
    });
  }

  const clear = $('weekClear');
  if (clear) {
    clear.addEventListener('click', async () => {
      if (!window.confirm('Clear every day of this week?')) return;
      state.plan.data.week = DAYS.map((name) => ({ day: name, meals: [] }));
      // The planner's report describes a week that no longer exists. Leaving
      // it on screen listing all seven days is why clearing looked as though
      // it had done nothing at all.
      auto.result = null;
      try {
        await savePlan();
        toast('Week cleared. Undo is on the Data tab.');
      } catch (err) {
        toast(err.message);
      }
      render();
    });
  }

  const build = $('weekShop');
  if (build) {
    build.addEventListener('click', async () => {
      const totals = {};
      const pantry = new Set(Object.keys(state.plan.data.pantry || {}));
      weekData().forEach((day) => (day.meals || []).forEach((m) => {
        if (m.on === false) return;   // a skipped meal is not shopped for
        const r = recipeById(m.recipeId);
        if (!r) return;
        (r.ingredients || []).forEach((i) => {
          if (pantry.has(i.food)) return;   // already on the shelf at home
          const line = totals[i.food] || (totals[i.food] = {
            aisle: i.aisle || 'pantry', woo: i.query || i.food,
            pack: i.pack || null, grams: 0, usedIn: [],
            loose: !!i.loose,
          });
          // What you eat, not what you cook. `m.servings` is already how many
          // servings that meal takes; multiplying by the batch size as well
          // bought four servings' worth of everything for every serving
          // planned -- four times the food, forty-two bags of spinach, and a
          // five hundred dollar week.
          line.grams += (i.gramsPerServing || 0) * (m.servings || 1);
          if (!line.usedIn.includes(r.name)) line.usedIn.push(r.name);
        });
      }));

      if (!Object.keys(totals).length) {
        $('weekOut').innerHTML =
          '<div class="err">Nothing planned yet, so there is nothing to buy.</div>';
        return;
      }
      Object.values(totals).forEach((l) => {
        l.grams = Math.round(l.grams);
        l.packsNeeded = l.pack ? Math.max(1, Math.ceil(l.grams / l.pack)) : null;
      });
      // Keep pictures and store links already attached to matching lines.
      const old = state.plan.data.shop || {};
      Object.keys(totals).forEach((k) => {
        if (old[k] && old[k].image) totals[k].image = old[k].image;
        if (old[k] && old[k].url) totals[k].url = old[k].url;
      });
      state.plan.data.shop = totals;
      state.plan.data.got = [];

      // Seed the prices the planner already worked the budget out from, so the
      // list opens with a total instead of $0.00 and a row of dashes. These
      // come from the catalogue, not from a fresh trip to the store, so it
      // costs nothing and Refresh prices still gets today's figures.
      let seeded = 0;
      try {
        const table = (await api('/ingredient-prices')).prices || {};
        const prices = state.plan.data.prices || {};
        const today = new Date().toISOString().slice(0, 10);
        Object.keys(totals).forEach((food) => {
          const known = table[food];
          if (!known || !known.price) return;
          const history = prices[food] || [];
          if (history.some((e) => e.date === today)) return;
          history.push({
            price: known.price, pack: known.pack, date: today,
            store: 'Woolworths (online)', source: 'catalogue',
            matched: known.product || '', url: known.url || '',
          });
          prices[food] = history;
          // The picture comes from the same product as the price, so a line
          // cannot end up showing one product and costing another.
          if (known.image) totals[food].image = known.image;
          if (known.url) totals[food].url = known.url;
          seeded += 1;
        });
        state.plan.data.prices = prices;
      } catch (_) { /* the list is still usable without them */ }

      await savePlan();
      $('weekOut').innerHTML = `<div class="note">Shopping list built:
        ${Object.keys(totals).length} items${pantry.size
          ? `, skipping ${pantry.size} already in your pantry` : ''}${seeded
          ? `, ${seeded} priced from the catalogue` : ''}. Open the
        <b>Shopping list</b> tab to check them off.</div>`;
    });
  }
}


/* ------------------------------------------------------- choose a recipe */

let chosen = [];

function optionCard(o) {
  const m = o.perServing || {};
  const cat = CAT_ORDER.includes(o.category) ? o.category : 'other';
  const notes = (o.notes || []).map((n) =>
    `<div class="tag warn" style="margin-top:6px">${esc(n)}</div>`).join('');
  return `<div class="day option" data-opt="${esc(o.option)}">
    <div class="row">
      <span class="opt-letter">${esc(o.option)}</span>
      <span class="dot cat-${esc(cat)}" title="${esc(CAT_LABEL[cat])}"></span>
      <h3 style="flex:1;min-width:0">${esc(o.name)}</h3>
    </div>
    <div class="macros num">
      <span><b>${Math.round(m.kcal)}</b> kcal</span>
      <span><b>${Math.round(m.p)}</b>g protein</span>
      <span><b>${Math.round(m.fb)}</b>g fibre</span>
      <span class="muted">makes ${o.servings}</span>
    </div>
    ${(o.ingredients || []).slice(0, 5).map((i) =>
      `<div class="meal">${esc(i.food)} <span class="num muted">${i.gramsPerServing} g</span></div>`
    ).join('')}
    ${(o.ingredients || []).length > 5
      ? `<div class="muted small" style="padding:4px 0">and ${o.ingredients.length - 5} more</div>` : ''}
    ${notes}
    <button class="tiny primary" data-take="${esc(o.option)}"
      style="margin-top:10px;width:100%">Keep this one</button>
  </div>`;
}

function renderChosen() {
  if (!chosen.length) return '';
  return `<div class="note" style="margin-top:14px">
    <b>Keeping ${chosen.length} recipe${chosen.length === 1 ? '' : 's'}:</b>
    ${chosen.map((r, i) => `<span class="tag ok">${esc(r.name)}
      <button class="ghost tiny" data-unkeep="${i}" aria-label="Remove">&times;</button></span>`).join(' ')}
    <div class="row" style="margin-top:10px">
      <button id="optSave" class="primary tiny">Save these to my library</button>
      <button id="optMore" class="tiny">Offer more</button>
    </div></div>`;
}

async function offerOptions(replace) {
  const btn = $('bOpts');
  btn.disabled = true;
  btn.textContent = 'Thinking…';
  try {
    const body = {
      // A fresh seed each time, so "Offer more" genuinely offers more.
      seed: state.plan.name + ':' + Date.now() + ':' + chosen.length,
      meals: 3,
      servings: Number($('bServ').value),
      kcal_per_serving: Number($('bKcal').value),
      protein_per_serving: Number($('bProt').value),
      diet: $('bDiet').value,
      cuisine: ($('bCuisine') || {}).value || 'any',
      exclude: $('bExcl').value.split(',').map((x) => x.trim()).filter(Boolean),
    };
    const res = await api('/recipes/options', { method: 'POST', body });
    lastOptions = res.options || [];
    $('bOut').innerHTML =
      `<h3 style="margin:0 0 4px">Pick one</h3>
       <p class="muted small" style="margin:0 0 12px">Three different mains,
         all built to your targets.</p>
       <div class="grid g2">${lastOptions.map(optionCard).join('')}</div>
       <div id="chosenOut">${renderChosen()}</div>`;
    wireOptions();
  } catch (err) {
    $('bOut').innerHTML = `<div class="err">${esc(err.message)}</div>`;
  } finally {
    btn.disabled = false;
    btn.textContent = 'Offer me choices';
  }
}

let lastOptions = [];

function wireOptions() {
  document.querySelectorAll('[data-take]').forEach((b) => {
    b.addEventListener('click', () => {
      const o = lastOptions.find((x) => x.option === b.dataset.take);
      if (!o || chosen.some((c) => c.name === o.name)) return;
      chosen.push(o);
      b.textContent = 'Kept';
      b.disabled = true;
      $('chosenOut').innerHTML = renderChosen();
      wireChosen();
    });
  });
  wireChosen();
}

function wireChosen() {
  document.querySelectorAll('[data-unkeep]').forEach((b) => {
    b.addEventListener('click', () => {
      chosen.splice(Number(b.dataset.unkeep), 1);
      $('chosenOut').innerHTML = renderChosen();
      wireChosen();
    });
  });
  const more = $('optMore');
  if (more) more.addEventListener('click', () => offerOptions());
  const save = $('optSave');
  if (save) {
    save.addEventListener('click', async () => {
      save.disabled = true;
      save.textContent = 'Saving…';
      const res = await api('/recipes/save-many',
        { method: 'POST', body: { recipes: chosen } });
      await loadRecipes();
      const n = chosen.length;
      chosen = [];
      $('bOut').innerHTML = `<div class="note">Saved ${res.saved} recipe${
        res.saved === 1 ? '' : 's'} to your library${
        res.skipped ? ` (${res.skipped} were already there)` : ''}.
        Rate them under <b>Recipes</b>, or put them on days under
        <b>Week</b>.</div>`;
    });
  }
}

/* ------------------------------------------------------------- find a recipe */

const found = { recipe: null, servings: null, system: 'metric', meal: '', nutrition: {} };

function viewFind() {
  return `<div class="card">
    <h2>Bring in a recipe</h2>
    <p class="sub">Paste the address of a recipe you like. It reads the
      ingredients, servings and times, converts between metric and imperial,
      and rescales to however many you are cooking for.</p>
    <div class="row">
      <input id="impUrl" placeholder="https://…" style="flex:1;min-width:220px"
        value="${esc((found.recipe || {}).sourceUrl || '')}">
      <button id="impGo" class="primary">Fetch</button>
    </div>
    <p class="muted small" style="margin:10px 0 0">
      Works with sites that publish structured recipe data, which most large
      cooking sites do. The recipe is saved to your library and credited to
      wherever it came from.</p>
    <div id="impOut" style="margin-top:16px">${found.recipe ? renderFound() : ''}</div>
  </div>`;
}

// A recipe's photograph lives on the site it came from, and the content
// security policy allows no such host. The server fetches it instead, which
// keeps the policy tight and means the recipe site is not told your address.
function remoteImage(url) {
  if (!url) return '';
  return '/api/image?url=' + encodeURIComponent(url);
}


function renderFound() {
  const r = found.recipe;
  const times = [
    r.prepTime ? `prep ${esc(r.prepTime)}` : '',
    r.cookTime ? `cook ${esc(r.cookTime)}` : '',
    r.totalTime ? `total ${esc(r.totalTime)}` : '',
  ].filter(Boolean).join(' · ');

  return `<div class="card" style="margin:0">
    <div class="row" style="align-items:flex-start">
      ${r.image ? `<img class="thumb" style="width:110px;height:110px"
        src="${esc(remoteImage(r.image))}" alt="" data-onfail="remove">` : ''}
      <div style="flex:1;min-width:0">
        <h3 style="margin:0">${esc(r.name)}</h3>
        <p class="muted small" style="margin:3px 0 0">
          ${times}${times && r.sourceName ? ' · ' : ''}
          ${r.sourceName ? `from <a href="${esc(r.sourceUrl)}" target="_blank"
            rel="noopener noreferrer">${esc(r.sourceName)}</a>` : ''}
          ${r.author ? ` · ${esc(r.author)}` : ''}</p>
      </div>
    </div>

    <div class="row" style="margin-top:14px">
      <label class="muted small">Serves
        <input type="number" id="impServ" min="1" max="50"
          value="${r.servings || 4}" style="width:64px;margin-left:6px"></label>
      <label class="muted small">Meal
        <select id="impMeal" style="margin-left:6px">${optionsFor(MEALS, found.meal)}</select></label>
      <div class="seg">
        <button class="${found.system === 'metric' ? 'on' : ''}" data-sys="metric">Metric</button>
        <button class="${found.system === 'imperial' ? 'on' : ''}" data-sys="imperial">Imperial</button>
      </div>
      <div style="flex:1"></div>
      <button id="impSave" class="primary tiny">Save to my library</button>
    </div>
    <div id="impNote" class="muted small" style="margin-top:8px"></div>

    <h4 style="margin:16px 0 6px">Ingredients</h4>
    ${(() => {
      const rows = importedRows(r);
      const totals = importedTotals(rows);
      return `${totals.unknown ? `<div class="warn">${totals.unknown}
        ingredient${totals.unknown === 1 ? ' has' : 's have'} no nutrition
        match, so ${totals.unknown === 1 ? 'it is' : 'they are'} missing from
        the totals below. The recipe still saves and shops correctly --
        it is only the kcal/protein figures that are short.</div>` : ''}
      ${(r.lines || []).map((l, i) => {
        const eq = (r.equivalents || [])[i];
        const orig = (r.original || [])[i];
        // The page's own wording is the authority. Ours agrees with it at the
        // published serving count and has to differ once it is scaled, so show
        // both rather than quietly replacing one with the other.
        const differs = orig && orig.trim() !== l.trim();
        const row = rows[i];
        return `<div class="meal ing-line">
          <span>${esc(l)}</span>
          ${eq ? `<span class="muted small">${esc(eq)}</span>` : ''}
          ${differs ? `<span class="muted small as-written"
            title="What the page says">page: ${esc(orig)}</span>` : ''}
          ${row && row.per100
            ? `<span class="tag ok">${Math.round((row.per100.kcal || 0) * (row.gramsPerServing || 0) / 100)} kcal</span>`
            : '<span class="tag stop">no nutrition</span>'}
        </div>`;
      }).join('')}
      ${rows.length ? `<div class="stats" style="margin-top:14px">
        <div class="stat"><div class="k">Per serving</div>
          <div class="v">${Math.round(totals.perServing.kcal)}<span class="muted"
            style="font-size:14px"> kcal</span></div></div>
        <div class="stat"><div class="k">Protein each</div>
          <div class="v">${Math.round(totals.perServing.p)}<span class="muted"
            style="font-size:14px"> g</span></div></div>
        <div class="stat"><div class="k">Fibre each</div>
          <div class="v">${Math.round(totals.perServing.fb)}<span class="muted"
            style="font-size:14px"> g</span></div></div>
      </div>` : ''}`;
    })()}

    ${(r.steps || []).length ? `<h4 style="margin:16px 0 6px">Method</h4>
      <ol class="steps">${r.steps.map((st) => `<li>${esc(st)}</li>`).join('')}</ol>
      <p class="muted small" style="margin-top:10px">Method as published by
        <a href="${esc(r.sourceUrl)}" target="_blank" rel="noopener noreferrer">
        ${esc(r.sourceName)}</a>.</p>` : ''}
  </div>`;
}

async function rescaleFound() {
  const servings = Math.max(1, Number(($('impServ') || {}).value) || 4);
  const res = await api('/recipes/rescale', {
    method: 'POST',
    body: { recipe: found.recipe, servings, system: found.system },
  });
  found.recipe = res.recipe;
  $('impOut').innerHTML = renderFound();
  wireFound();
}

function wireFound() {
  const serv = $('impServ');
  if (serv) serv.addEventListener('change', rescaleFound);

  const meal = $('impMeal');
  if (meal) meal.addEventListener('change', () => { found.meal = meal.value; });

  document.querySelectorAll('[data-sys]').forEach((b) => {
    b.addEventListener('click', () => {
      found.system = b.dataset.sys;
      rescaleFound();
    });
  });

  const save = $('impSave');
  if (save) {
    save.addEventListener('click', async () => {
      const r = found.recipe;
      const rows = importedRows(r);
      const totals = importedTotals(rows);
      save.disabled = true;
      save.textContent = 'Saving…';
      try {
        await api('/recipes/save-many', {
          method: 'POST',
          body: {
            recipes: [{
              name: r.name,
              servings: r.servings,
              meal: found.meal || undefined,
              perServing: {
                kcal: Math.round(totals.perServing.kcal),
                p: Math.round(totals.perServing.p * 10) / 10,
                c: Math.round(totals.perServing.c * 10) / 10,
                f: Math.round(totals.perServing.f * 10) / 10,
                fb: Math.round(totals.perServing.fb * 10) / 10,
              },
              ingredients: rows,
              steps: r.steps || [],
              storage: '',
              reheat: [],
              source: r.sourceUrl,
              sourceName: r.sourceName,
              imported: true,
              image: r.image || '',
              // For the Sunday cook sheet -- the site's own numbers, kept
              // exactly as it stated them, never re-derived from the prose.
              prepTime: r.prepTime || '', cookTime: r.cookTime || '',
              totalTime: r.totalTime || '',
              prepMinutes: r.prepMinutes ?? null,
              cookMinutes: r.cookMinutes ?? null,
              totalMinutes: r.totalMinutes ?? null,
            }],
          },
        });
        await loadRecipes();
        save.textContent = 'Saved';
      } catch (err) {
        save.disabled = false;
        save.textContent = 'Save to my library';
        window.alert(err.message);
      }
    });
  }
}

function wireFindRecipe() {
  const go = $('impGo');
  const url = $('impUrl');
  const run = async () => {
    const value = (url.value || '').trim();
    if (!value) return;
    go.disabled = true;
    go.textContent = 'Fetching…';
    $('impOut').innerHTML = '<div class="note">Reading that page…</div>';
    try {
      const res = await api('/recipes/import', {
        method: 'POST',
        body: { url: value, system: found.system },
      });
      found.recipe = res.recipe;
      await loadImportEstimates(res.recipe);
      $('impOut').innerHTML = renderFound();
      wireFound();
    } catch (err) {
      $('impOut').innerHTML = `<div class="err">${esc(err.message)}</div>`;
    } finally {
      go.disabled = false;
      go.textContent = 'Fetch';
    }
  };
  if (go) go.addEventListener('click', run);
  if (url) url.addEventListener('keydown', (e) => { if (e.key === 'Enter') run(); });
  if (found.recipe) wireFound();
}

/* ---------------------------------------------------------------- scanner */

const scan = {
  stream: null, track: null, running: false, detector: null,
  last: '', lastAt: 0, streak: { code: '', n: 0 },
  result: null, auto: true, added: [], busy: false, torch: false,
};

// Two readings of the same number before it counts. At this frame rate that is
// under a fifth of a second -- fast enough to feel instant, strict enough that
// a barcode caught edge-on does not add the wrong tin.
const SCAN_INTERVAL_MS = 90;
const SCAN_AGREE = 2;
// Reading the same code again is normally the camera not having moved yet.
// After a few seconds it means a second one of the same thing.
const SCAN_REPEAT_MS = 3000;

// Chrome on Android ships a barcode detector, so no library is needed and
// nothing extra is downloaded. Everywhere else falls back to typing the number.
function scannerSupported() {
  return typeof window.BarcodeDetector === 'function'
    && !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia);
}

function scanButton() {
  if (!scannerSupported()) return '';
  return `<button id="scanOpen" class="primary">Scan a barcode</button>`;
}

function scannerSheet() {
  return `<div class="sheet-back" id="scanBack"></div>
    <div class="sheet scan-sheet" role="dialog" aria-label="Scan a barcode">
      <div class="sheet-top">
        <div><h3 style="margin:0">Point at a barcode</h3>
          <p class="muted small" id="scanHint" style="margin:2px 0 0">
            Starting the camera&hellip;</p></div>
        <button class="ghost" id="scanClose">Done</button>
      </div>
      <div class="scan-view">
        <video id="scanVideo" playsinline muted autoplay></video>
        <div class="scan-frame"></div>
        <div class="scan-flash" id="scanFlash"></div>
      </div>
      <div class="scan-tools">
        <label class="scan-toggle"><input type="checkbox" id="scanAuto" checked>
          <span>Add as I scan</span></label>
        <div style="flex:1"></div>
        <button class="ghost tiny" id="scanTorch" hidden>Light</button>
      </div>
      <div id="scanOut"></div>
      <div id="scanList" class="scan-list"></div>
    </div>`;
}

function scanHint(text) {
  const el = $('scanHint');
  if (el) el.textContent = text;
}

function scanFlash() {
  const el = $('scanFlash');
  if (!el) return;
  el.classList.remove('lit');
  // Restart the animation rather than let a second scan land on a class that
  // is already applied and therefore does nothing.
  void el.offsetWidth;
  el.classList.add('lit');
}

async function openScanner() {
  const host = document.createElement('div');
  host.id = 'scanHost';
  host.innerHTML = scannerSheet();
  document.body.appendChild(host);

  scan.auto = true;
  scan.added = [];
  scan.last = '';
  scan.lastAt = 0;
  scan.streak = { code: '', n: 0 };
  scan.result = null;
  scan.torch = false;

  const close = () => {
    stopScanner();
    host.remove();
    // The list behind the sheet is stale by however much was scanned into it.
    if (scan.added.length) render();
  };
  $('scanBack').addEventListener('click', close);
  $('scanClose').addEventListener('click', close);
  $('scanAuto').addEventListener('change', (e) => {
    scan.auto = e.target.checked;
    scanHint(scan.auto
      ? 'Hold a barcode in the frame — it adds itself.'
      : 'Hold a barcode in the frame.');
  });

  const video = $('scanVideo');
  try {
    scan.stream = await navigator.mediaDevices.getUserMedia({
      // The rear camera is the one pointing at the tin. Ask for a full HD
      // frame: a barcode is thin black lines, and at 640px wide the lines of
      // a supermarket EAN merge into grey unless the phone is held close and
      // still -- which is exactly the fiddliness worth removing.
      video: {
        facingMode: { ideal: 'environment' },
        width: { ideal: 1920 }, height: { ideal: 1080 },
      },
      audio: false,
    });
    video.srcObject = scan.stream;
    await video.play();
    scan.track = scan.stream.getVideoTracks()[0] || null;

    if (scan.track) {
      // A barcode at arm length is a close subject. Left alone the camera
      // hunts for focus and only settles once nothing is moving -- the other
      // half of having to hold still. These are best-effort hints; a camera
      // that does not offer them simply ignores them.
      try {
        await scan.track.applyConstraints({
          advanced: [{ focusMode: 'continuous' }, { exposureMode: 'continuous' }],
        });
      } catch (_) { /* the camera decides for itself, which is fine */ }

      const caps = scan.track.getCapabilities
        ? (scan.track.getCapabilities() || {}) : {};
      if (caps.torch) {
        const torch = $('scanTorch');
        torch.hidden = false;
        torch.addEventListener('click', async () => {
          scan.torch = !scan.torch;
          try {
            await scan.track.applyConstraints({ advanced: [{ torch: scan.torch }] });
          } catch (_) { scan.torch = false; }
          torch.classList.toggle('primary', scan.torch);
        });
      }
    }
    scanHint('Hold a barcode in the frame — it adds itself.');
  } catch (err) {
    scanHint('Camera unavailable.');
    $('scanOut').innerHTML = `<div class="err">${esc(
      err && err.name === 'NotAllowedError'
        ? 'Camera permission was declined. Allow it for this site, or type the number in instead.'
        : 'Could not start the camera: ' + (err.message || err))}</div>
      ${manualEntryHtml()}`;
    wireManualEntry();
    return;
  }

  let formats = ['ean_13', 'ean_8', 'upc_a', 'upc_e', 'code_128', 'itf'];
  try {
    const available = await window.BarcodeDetector.getSupportedFormats();
    const usable = formats.filter((f) => available.includes(f));
    if (usable.length) formats = usable;
  } catch (_) { /* take the list as written */ }
  scan.detector = new window.BarcodeDetector({ formats });

  scan.running = true;
  tickScanner(video);
}

async function tickScanner(video) {
  if (!scan.running) return;
  try {
    // Skip frames while a lookup is in flight: decoding underneath it only
    // competes for the same phone and cannot act on what it finds.
    if (!scan.busy && video.readyState >= 2) {
      const codes = await scan.detector.detect(video);
      const hit = codes.find((c) => (c.rawValue || '').length >= 6);
      if (hit) acceptScan(hit.rawValue);
    }
  } catch (_) { /* a frame that will not decode is normal */ }
  if (scan.running) setTimeout(() => tickScanner(video), SCAN_INTERVAL_MS);
}

function acceptScan(code) {
  if (scan.streak.code === code) scan.streak.n += 1;
  else scan.streak = { code, n: 1 };
  if (scan.streak.n < SCAN_AGREE) return;

  const now = Date.now();
  if (code === scan.last && now - scan.lastAt < SCAN_REPEAT_MS) {
    scan.lastAt = now;
    return;
  }
  scan.last = code;
  scan.lastAt = now;
  if (navigator.vibrate) navigator.vibrate(35);
  scanFlash();
  handleScan(code);
}

function stopScanner() {
  scan.running = false;
  if (scan.track && scan.torch) {
    try { scan.track.applyConstraints({ advanced: [{ torch: false }] }); }
    catch (_) { /* the track is about to stop anyway */ }
  }
  if (scan.stream) {
    scan.stream.getTracks().forEach((t) => t.stop());
    scan.stream = null;
  }
  scan.track = null;
}

function manualEntryHtml() {
  return `<div class="row" style="margin-top:10px">
    <input id="scanManual" inputmode="numeric" placeholder="or type the number"
      style="flex:1;min-width:150px">
    <button id="scanManualGo">Look up</button>
  </div>`;
}

function wireManualEntry() {
  const go = $('scanManualGo');
  const input = $('scanManual');
  if (!go || !input) return;
  const run = () => handleScan(input.value.trim());
  go.addEventListener('click', run);
  input.addEventListener('keydown', (e) => { if (e.key === 'Enter') run(); });
}

async function handleScan(code) {
  const out = $('scanOut');
  scan.busy = true;
  scanHint('Looking that up…');
  try {
    const res = await api('/barcode/' + encodeURIComponent(code));
    scan.result = res;
    if (scan.auto && res.status === 'success') {
      // The point of scanning a trolley is not stopping between tins.
      out.innerHTML = '';
      await addScanned(res);
      scanHint('Added. Point at the next one.');
    } else {
      out.innerHTML = renderScan(res);
      wireScanResult();
      scanHint(res.status === 'success'
        ? 'Tap add, or point at the next one.'
        : 'Nothing found for that code.');
    }
  } catch (err) {
    out.innerHTML = `<div class="err">${esc(err.message)}</div>${manualEntryHtml()}`;
    wireManualEntry();
    // Let the same code be tried again after a failure.
    scan.last = '';
  } finally {
    scan.busy = false;
  }
}

function scannedBody(res) {
  const p = res.product;
  const n = res.nutrition;
  const name = (p && p.name) || (n && n.name) || 'Scanned item';
  return p && p.stockcode
    ? { store: p.store || 'woolworths', stockcode: String(p.stockcode),
        aisle: guessAisle(p.name) }
    : { food: name, aisle: guessAisle(name), pack: (n && n.pack_g) || null };
}

async function addScanned(res) {
  const p = res.product;
  const n = res.nutrition;
  const name = (p && p.name) || (n && n.name) || 'Scanned item';
  const saved = await api('/plans/' + state.planId + '/shop-items',
    { method: 'POST', body: scannedBody(res) });
  await loadPlan();

  // Show the price the server settled on, which for anything Woolworths does
  // not stock is a lookup it did on the way in rather than the scan's figure.
  const food = (saved && saved.food) || name;
  const prices = (state.plan && state.plan.data && state.plan.data.prices) || {};
  const history = prices[food];
  const priced = history && history.length ? history[history.length - 1] : null;

  scan.added.unshift({
    food,
    name,
    price: priced && priced.price != null
      ? priced.price : ((p && p.pack_price) || null),
    image: (p && p.image) || (n && n.image) || '',
  });
  renderScanList();
}

function renderScanList() {
  const list = $('scanList');
  if (!list) return;
  if (!scan.added.length) { list.innerHTML = ''; return; }
  list.innerHTML = `<h4 class="pick-head">Added this trip (${scan.added.length})</h4>
    ${scan.added.map((item) => `<div class="scan-row">
      ${thumb({ image: item.image, name: item.name })}
      <div style="flex:1;min-width:0">
        <div class="clip">${esc(item.name)}</div>
        <div class="muted small num">${item.price != null
          ? money(item.price) : 'priced on the list'}</div>
      </div>
      <button class="ghost tiny" data-unscan="${esc(item.food)}">remove</button>
    </div>`).join('')}`;

  list.querySelectorAll('[data-unscan]').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const food = btn.dataset.unscan;
      btn.disabled = true;
      try {
        await api('/plans/' + state.planId + '/shop-items/'
          + encodeURIComponent(food), { method: 'DELETE' });
        scan.added = scan.added.filter((i) => i.food !== food);
        await loadPlan();
        renderScanList();
        // Scanning it again should work, not be swallowed as a repeat.
        scan.last = '';
      } catch (err) {
        btn.disabled = false;
        scanHint(err.message);
      }
    });
  });
}

function renderScan(res) {
  if (res.status !== 'success') {
    return `<div class="warn">${esc(res.message || 'Nothing found for that code.')}</div>
      ${manualEntryHtml()}`;
  }

  const p = res.product;
  const n = res.nutrition;
  const macros = n && n.nutrition ? n.nutrition : null;
  const name = (p && p.name) || (n && n.name) || 'Unnamed product';
  const image = (p && p.image) || (n && n.image) || '';

  const price = p && p.pack_price
    ? `<div class="row">${shelfTicket(ticketFrom(p), p.per_kg)}</div>`
    : '<p class="muted small" style="margin:0">No price found at Woolworths.</p>';

  const nutrition = macros ? `<div class="macros num" style="margin-top:10px">
      ${macros.kcal != null ? `<span><b>${macros.kcal}</b> kcal</span>` : ''}
      ${macros.p != null ? `<span><b>${macros.p}</b>g protein</span>` : ''}
      ${macros.c != null ? `<span><b>${macros.c}</b>g carb</span>` : ''}
      ${macros.f != null ? `<span><b>${macros.f}</b>g fat</span>` : ''}
      ${macros.fb != null ? `<span><b>${macros.fb}</b>g fibre</span>` : ''}
      <span class="muted">per 100g</span></div>` : '';

  const where = (res.sources || []).map((sname) =>
    `<span class="tag">${esc({ catalogue: 'already indexed',
      woolworths: 'Woolworths', openfoodfacts: 'Open Food Facts' }[sname] || sname)}</span>`
  ).join(' ');

  return `<div class="card" style="margin:0">
    <div class="row" style="align-items:flex-start">
      ${thumb({ image, name })}
      <div style="flex:1;min-width:0">
        <b>${esc(name)}</b>
        <div class="muted small">${esc((p && p.package_size) || (n && n.package_size) || '')}
          &middot; ${esc(res.barcode)}</div>
        <div style="margin-top:6px">${price}</div>
      </div>
    </div>
    ${nutrition}
    <div class="row" style="margin-top:12px">${where}<div style="flex:1"></div>
      <button class="tiny primary" id="scanAdd">Add to shopping list</button>
    </div>
  </div>`;
}

function wireScanResult() {
  const add = $('scanAdd');
  if (!add) return;
  add.addEventListener('click', async () => {
    add.disabled = true;
    add.textContent = 'Adding…';
    try {
      await addScanned(scan.result);
      $('scanOut').innerHTML = '';
      scanHint('Added. Point at the next one.');
    } catch (err) {
      add.disabled = false;
      add.textContent = 'Add to shopping list';
      $('scanOut').insertAdjacentHTML('beforeend',
        `<div class="err" style="margin-top:8px">${esc(err.message)}</div>`);
    }
  });
}

const MEALS = [
  { id: '', label: 'Any meal' },
  { id: 'breakfast', label: 'Breakfast' },
  { id: 'lunch', label: 'Lunch' },
  { id: 'dinner', label: 'Dinner' },
];

const DIETS = [
  { id: 'any', label: 'No restriction' },
  { id: 'pescatarian', label: 'Pescatarian' },
  { id: 'vegetarian', label: 'Vegetarian' },
  { id: 'vegan', label: 'Vegan' },
  { id: 'keto', label: 'Keto' },
];

function optionsFor(list, chosen) {
  return list.map((o) => `<option value="${esc(o.id)}"${
    o.id === chosen ? ' selected' : ''}>${esc(o.label)}</option>`).join('');
}

function mealTag(r) {
  const meal = r && r.meal;
  if (!meal) return '';
  return `<span class="tag when when-${esc(meal)}">${
    esc(meal[0].toUpperCase() + meal.slice(1))}</span>`;
}


/* --------------------------------------------------------- ingredient photos

A generated recipe has no photograph of its own, and inventing one would be a
picture of a dish nobody cooked. What is both honest and more useful is showing
what actually goes in it -- the real product shots, already fetched for pricing.

The map is small and changes rarely, so it is kept in the browser between
visits and refreshed weekly rather than on every load.                        */

const PHOTO_KEY = 'shelfplan.foodImages';
const PHOTO_MAX_AGE_MS = 7 * 24 * 60 * 60 * 1000;
const photos = { map: {}, loading: null };

function readStoredPhotos() {
  try {
    const raw = localStorage.getItem(PHOTO_KEY);
    if (!raw) return null;
    const held = JSON.parse(raw);
    if (!held || !held.at || Date.now() - held.at > PHOTO_MAX_AGE_MS) return null;
    return held.map || null;
  } catch (_) { return null; }
}

async function loadFoodImages(force) {
  if (photos.loading) return photos.loading;
  if (!force) {
    const held = readStoredPhotos();
    if (held) { photos.map = held; return held; }
  }
  photos.loading = (async () => {
    try {
      const res = await api('/food-images');
      photos.map = res.images || {};
      try {
        localStorage.setItem(PHOTO_KEY,
          JSON.stringify({ at: Date.now(), map: photos.map }));
      } catch (_) { /* a private window has no room; the map still works */ }
      if (Object.keys(photos.map).length) render();
    } catch (_) { /* pictures are a bonus, never a reason to fail */ }
    photos.loading = null;
    return photos.map;
  })();
  return photos.loading;
}

// Longest match first, so "sweet potato" is not read as "potato" and "spring
// onion" is not read as "onion".
const GLYPHS = [
  ['sweet potato', '🍠'], ['spring onion', '🧅'], ['brown onion', '🧅'],
  ['red onion', '🧅'], ['bok choy', '🥬'], ['baby spinach', '🥬'],
  ['brussels sprout', '🥬'], ['snow pea', '🫛'], ['green bean', '🫛'],
  ['kidney bean', '🫘'], ['black bean', '🫘'], ['butter bean', '🫘'],
  ['red lentil', '🫘'], ['brown lentil', '🫘'], ['chickpea', '🫘'],
  ['cherry tomato', '🍅'], ['olive oil', '🫒'], ['sesame oil', '🫒'],
  ['peanut butter', '🥜'], ['chia seed', '🌱'], ['whey protein', '🥛'],
  ['greek yoghurt', '🥛'], ['cottage cheese', '🧀'], ['parmesan', '🧀'],
  ['feta', '🧀'], ['haloumi', '🧀'], ['coconut milk', '🥥'],
  ['curry paste', '🌶️'], ['smoked paprika', '🌶️'], ['garam masala', '🌶️'],
  ['ground cumin', '🌶️'], ['dried oregano', '🌿'], ['fresh ginger', '🫚'],
  ['tomato passata', '🍅'], ['soy sauce', '🍶'], ['fish sauce', '🍶'],
  ['oyster sauce', '🍶'], ['miso', '🍶'], ['mirin', '🍶'],
  ['stock cube', '🧊'], ['corn tortilla', '🌯'], ['wholemeal wrap', '🌯'],
  ['wholegrain bread', '🍞'], ['rolled oats', '🥣'], ['polenta', '🌽'],
  ['corn kernel', '🌽'], ['couscous', '🍚'], ['bulgur', '🍚'],
  ['pearl barley', '🍚'], ['quinoa', '🍚'], ['basmati', '🍚'],
  ['jasmine rice', '🍚'], ['brown rice', '🍚'], ['cauliflower rice', '🥦'],
  ['zucchini noodle', '🥒'], ['konjac noodle', '🍜'], ['soba', '🍜'],
  ['udon', '🍜'], ['egg noodle', '🍜'], ['rice noodle', '🍜'],
  ['pasta', '🍝'], ['gnocchi', '🥟'], ['tofu', '🧊'],
  ['chicken', '🍗'], ['turkey', '🍗'], ['beef', '🥩'], ['lamb', '🥩'],
  ['pork', '🥓'], ['bacon', '🥓'], ['salmon', '🐟'], ['tuna', '🐟'],
  ['white fish', '🐟'], ['prawn', '🦐'], ['egg', '🥚'], ['milk', '🥛'],
  ['butter', '🧈'], ['tahini', '🥜'], ['almond', '🌰'],
  ['broccoli', '🥦'], ['cauliflower', '🥦'], ['cabbage', '🥬'],
  ['silverbeet', '🥬'], ['kale', '🥬'], ['lettuce', '🥬'],
  ['spinach', '🥬'], ['capsicum', '🫑'], ['zucchini', '🥒'],
  ['cucumber', '🥒'], ['eggplant', '🍆'], ['mushroom', '🍄'],
  ['carrot', '🥕'], ['potato', '🥔'], ['pumpkin', '🎃'],
  ['tomato', '🍅'], ['onion', '🧅'], ['garlic', '🧄'], ['leek', '🧅'],
  ['celery', '🥬'], ['asparagus', '🥬'], ['banana', '🍌'],
  ['berries', '🫐'], ['berry', '🫐'], ['avocado', '🥑'], ['lemon', '🍋'],
  ['pea', '🫛'], ['corn', '🌽'], ['salt', '🧂'], ['flour', '🌾'],
  ['oat', '🥣'], ['rice', '🍚'], ['bean', '🫘'], ['fish', '🐟'],
  ['cheese', '🧀'], ['bread', '🍞'], ['oil', '🫒'], ['sauce', '🍶'],
];

function foodGlyph(name) {
  const key = String(name || '').toLowerCase();
  for (const [needle, glyph] of GLYPHS) {
    if (key.includes(needle)) return glyph;
  }
  return '';
}


// Ingredient names carry the state they are bought in -- "Chicken breast, raw",
// "Peas, frozen" -- which is right on a shopping list and noise under a photo.
function shortFood(name) {
  return String(name || '').split(',')[0];
}

function foodPhoto(name, cls, fallbackSrc) {
  // A written-your-own recipe names store products, which the photo map has
  // never heard of. It carries its own picture instead.
  const src = photos.map[name] || fallbackSrc;
  const label = shortFood(name);
  if (!src) {
    // A letter is not a picture of a cauliflower. Where the catalogue has no
    // photograph -- a food nobody has searched for yet, or one the store
    // ships without an image -- a glyph at least says what kind of thing it
    // is, and needs nothing fetched to do it.
    return `<span class="food-pic none ${cls || ''}" aria-hidden="true"
      >${foodGlyph(name) || esc(label.slice(0, 1).toUpperCase())}</span>`;
  }
  return `<img class="food-pic ${cls || ''}" src="${esc(src)}" alt=""
    decoding="async" data-onfail="glyph" data-fail-tag="span"
    data-fail-class="food-pic none ${esc(cls || '')}"
    data-fail-mark="${esc(foodGlyph(name) || '')}">`;
}

// The dish in four pictures: what it is built on, then whatever else there is
// most of. Sauces and oils are skipped -- a photograph of a bottle of oil tells
// you nothing about the meal.
// One picture is enough on a planned day -- the row is already carrying a
// name, a serving count and a calorie figure.
// The ingredient list, at the servings actually planned for that day. This is
// the part that makes a day readable: "chicken 200g, rice 55g, broccoli 150g"
// tells you what Tuesday is in a way that "Chicken and rice bowl" does not.
function mealIngredients(r, mult) {
  const items = (r.ingredients || []).filter((i) => i.gramsPerServing);
  if (!items.length) return '';
  return `<ul class="meal-ing num">${items.map((i) => `<li>
      <span>${esc(shortFood(i.food))}</span>
      <span>${Math.round(i.gramsPerServing * mult)} g</span>
    </li>`).join('')}</ul>`;
}


function mealThumb(r) {
  const items = (r.ingredients || []);
  const lead = items.find((i) => i.role === 'protein')
    || items.find((i) => i.role === 'base');
  return lead ? foodPhoto(lead.food, 'tiny', lead.image) : '';
}


function recipeStrip(r) {
  const items = (r.ingredients || []).filter(
    (i) => i.role !== 'fat' && i.role !== 'sauce');
  const wanted = [];
  ['protein', 'base', 'veg'].forEach((role) => {
    const hit = items.find((i) => i.role === role);
    if (hit) wanted.push(hit);
  });
  items.forEach((i) => {
    if (wanted.length < 4 && !wanted.includes(i)) wanted.push(i);
  });
  if (!wanted.length) return '';


  return `<div class="recipe-strip">${wanted.map((i) => `
    <figure class="strip-cell">
      ${foodPhoto(i.food, 'big', i.image)}
      <figcaption>${esc(shortFood(i.food))}</figcaption>
    </figure>`).join('')}</div>`;
}

/* ------------------------------------------------------------ the recipe book

The builder answers "what should I eat to hit these numbers". This answers the
other question people actually ask, which is "show me what there is". Every
combination the themes can make is walkable -- a couple of thousand per theme --
so it pages rather than loading the lot.                                      */

const book = { cuisine: 'any', category: '', meal: '', diet: 'any',
               recipes: [], total: 0, next: 0, busy: false, open: false };

function bookPanel() {
  if (!book.open) {
    return `<div class="card">
      <div class="row" style="align-items:baseline">
        <div style="flex:1;min-width:0">
          <h2 style="margin:0">The recipe book</h2>
          <p class="sub" style="margin:4px 0 0">Thousands of dishes across nine
            themes. Browse them instead of describing what you want.</p>
        </div>
        <button id="bookOpen" class="primary">Open the book</button>
      </div></div>`;
  }

  const themes = (state.cuisines || [{ id: 'any', label: 'No theme' }]);
  const grid = book.recipes.length
    ? `<div class="book-grid">${book.recipes.map(bookTile).join('')}</div>`
    : (book.busy ? '' : '<p class="muted">Nothing matches those filters.</p>');

  return `<div class="card">
    <div class="row" style="align-items:baseline">
      <h2 style="flex:1;min-width:0;margin:0">The recipe book</h2>
      <button class="ghost tiny" id="bookClose">Close</button>
    </div>
    <div class="grid g2" style="margin-top:12px">
      <div>
        <label for="bookMeal">Meal</label>
        <select id="bookMeal">${optionsFor(MEALS, book.meal)}</select>
      </div>
      <div>
        <label for="bookCuisine">Theme</label>
        <select id="bookCuisine">${themes.map((c) =>
          `<option value="${esc(c.id)}" ${c.id === book.cuisine ? 'selected' : ''}
            >${esc(c.label)}</option>`).join('')}</select>
      </div>
      <div>
        <label for="bookDiet">Diet</label>
        <select id="bookDiet">${optionsFor(DIETS, book.diet)}</select>
      </div>
      <div>
        <label for="bookCat">Kind</label>
        <select id="bookCat">
          <option value="">Anything</option>
          ${CAT_ORDER.map((c) => `<option value="${esc(c)}"
            ${c === book.category ? 'selected' : ''}>${esc(CAT_LABEL[c])}</option>`).join('')}
        </select>
      </div>
    </div>
    <p class="muted small" style="margin:10px 0 0">
      ${book.total ? `${book.total.toLocaleString()} dishes in this theme.` : ''}
      ${book.recipes.length ? `Showing ${book.recipes.length}.` : ''}</p>
    ${grid}
    ${book.busy ? '<div class="note" style="margin-top:12px">Composing&hellip;</div>' : ''}
    ${book.next != null && book.recipes.length ? `<div class="row" style="margin-top:14px">
      <button id="bookMore" ${book.busy ? 'disabled' : ''}>Show me more</button>
      </div>` : ''}
  </div>`;
}

function bookTile(r) {
  const per = r.perServing || {};
  const cat = CAT_ORDER.includes(r.category) ? r.category : 'other';
  return `<article class="book-tile">
    <div class="tile-pics">${(r.ingredients || [])
      .filter((i) => i.role === 'protein' || i.role === 'base' || i.role === 'veg')
      .slice(0, 3).map((i) => foodPhoto(i.food, 'tile', i.image)).join('')}</div>
    <div class="tile-body">
      <div class="row" style="gap:6px;align-items:flex-start">
        <span class="dot cat-${esc(cat)}" style="margin-top:5px"></span>
        <b style="flex:1;min-width:0">${esc(r.name)}</b>
      </div>
      <div class="tile-tags">${mealTag(r)}</div>
      <div class="macros num small">
        <span><b>${Math.round(per.kcal || 0)}</b> kcal</span>
        <span><b>${Math.round(per.p || 0)}</b>g protein</span>
        <span><b>${Math.round(per.fb || 0)}</b>g fibre</span>
      </div>
      <div class="row" style="margin-top:auto;padding-top:8px">
        <button class="ghost tiny" data-bookopen="${esc(r.id)}">See it</button>
        <div style="flex:1"></div>
        <button class="tiny primary" data-booksave="${esc(r.id)}">Save</button>
      </div>
    </div>
  </article>`;
}

async function loadBook(reset) {
  if (book.busy) return;
  book.busy = true;
  if (reset) { book.recipes = []; book.next = 0; book.total = 0; }
  render();
  try {
    const res = await api('/recipes/browse?cuisine=' + encodeURIComponent(book.cuisine)
      + '&category=' + encodeURIComponent(book.category)
      + '&meal=' + encodeURIComponent(book.meal)
      + '&diet=' + encodeURIComponent(book.diet)
      + '&limit=24&offset=' + (book.next || 0));
    book.total = res.total;
    book.next = res.nextOffset;
    book.recipes = book.recipes.concat(res.recipes || []);
  } catch (err) {
    toast(err.message);
  }
  book.busy = false;
  render();
}

function wireBook() {
  const open = $('bookOpen');
  if (open) {
    open.addEventListener('click', () => {
      book.open = true;
      loadBook(true);
    });
    return;
  }
  const close = $('bookClose');
  if (close) close.addEventListener('click', () => { book.open = false; render(); });

  const cuisine = $('bookCuisine');
  if (cuisine) cuisine.addEventListener('change', () => {
    book.cuisine = cuisine.value;
    loadBook(true);
  });
  const cat = $('bookCat');
  if (cat) cat.addEventListener('change', () => {
    book.category = cat.value;
    loadBook(true);
  });
  const meal = $('bookMeal');
  if (meal) meal.addEventListener('change', () => {
    book.meal = meal.value;
    loadBook(true);
  });
  const bdiet = $('bookDiet');
  if (bdiet) bdiet.addEventListener('change', () => {
    book.diet = bdiet.value;
    loadBook(true);
  });
  const more = $('bookMore');
  if (more) more.addEventListener('click', () => loadBook(false));

  document.querySelectorAll('[data-bookopen]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const r = book.recipes.find((x) => x.id === btn.dataset.bookopen);
      if (r) showRecipeSheet(r);
    });
  });
  document.querySelectorAll('[data-booksave]').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const r = book.recipes.find((x) => x.id === btn.dataset.booksave);
      if (!r) return;
      btn.disabled = true;
      btn.textContent = 'Saving…';
      try {
        const res = await api('/recipes/save-many',
          { method: 'POST', body: { recipes: [r] } });
        await loadRecipes();
        btn.textContent = res.saved ? 'In your library' : 'Already saved';
      } catch (err) {
        btn.disabled = false;
        btn.textContent = 'Save';
        toast(err.message);
      }
    });
  });
}

function showRecipeSheet(r) {
  const host = document.createElement('div');
  host.id = 'recipeHost';
  host.innerHTML = `<div class="sheet-back" id="recBack"></div>
    <div class="sheet" role="dialog" aria-label="${esc(r.name)}">
      <div class="sheet-top">
        <h3 style="margin:0;flex:1;min-width:0">${esc(r.name)}</h3>
        <button class="ghost" id="recClose">Close</button>
      </div>
      <div class="sheet-body">${recipeCard(r, {})}</div>
    </div>`;
  document.body.appendChild(host);
  const shut = () => host.remove();
  $('recBack').addEventListener('click', shut);
  $('recClose').addEventListener('click', shut);
}

/* ----------------------------------------------------- planning a whole week

The server has been able to do this since the daily targets went in; there was
simply no way to ask it from the page. Give it a calorie ceiling and protein
and fibre floors and it fills seven days, composing whatever the library is
missing rather than telling you to go and build recipes first.               */

const auto = { busy: false, result: null, show: false };

const cookSheet = { show: false, data: null, busy: false, error: '' };

const DEVICE_LABEL = {
  oven: 'Oven', stovetop: 'Stovetop', assemble: 'No cooking', blender: 'Blender',
};

function clockLabel(totalMinutes) {
  const h = Math.floor(totalMinutes / 60);
  const m = Math.round(totalMinutes % 60);
  return h ? `${h}h ${m}m` : `${m} min`;
}

function cookSheetPanel() {
  const d = cookSheet.data;
  return `<div class="card auto-card">
    <div class="row" style="align-items:baseline">
      <div style="flex:1;min-width:0">
        <h2 style="margin:0">Sunday cook sheet</h2>
        <p class="sub" style="margin:4px 0 0">What the current week actually
          takes to cook -- one thing at a time on the oven, two on the stove,
          everything else fitted in around them.</p>
      </div>
      <button class="ghost tiny" id="cookRefresh" ${cookSheet.busy ? 'disabled' : ''}>${
        cookSheet.busy ? 'Working…' : 'Refresh'}</button>
    </div>
    ${cookSheet.error ? `<div class="err" style="margin-top:12px">${esc(cookSheet.error)}</div>` : ''}
    ${!d ? '<p class="muted small" style="margin-top:12px">Loading…</p>' : (
      !d.steps.length
        ? `<p class="muted" style="margin-top:12px">${esc(d.message || 'Nothing planned yet.')}</p>`
        : `<div class="stats" style="margin-top:14px">
             <div class="stat"><div class="k">Dishes to cook</div>
               <div class="v">${d.dishCount}</div></div>
             <div class="stat"><div class="k">Start to finish</div>
               <div class="v">${clockLabel(d.totalMinutes)}</div></div>
           </div>
           <div class="scroll" style="margin-top:12px"><table>
             <thead><tr><th>Clock</th><th>Dish</th><th>Where</th><th class="r">Batch</th></tr></thead>
             <tbody>${d.steps.map((s) => `<tr>
               <td class="num" style="white-space:nowrap">${clockLabel(s.atMinute)}</td>
               <td><b>${esc(s.name)}</b>
                 <div class="muted small">${esc(s.note)} &middot; eaten ${
                   s.sittings} time${s.sittings === 1 ? '' : 's'} this week</div></td>
               <td class="muted small">${esc(DEVICE_LABEL[s.device] || s.device)}</td>
               <td class="r num">${s.batches}&times;</td>
             </tr>`).join('')}</tbody>
           </table></div>`
    )}
  </div>`;
}

async function loadCookSheet() {
  cookSheet.busy = true;
  cookSheet.error = '';
  render();
  try {
    cookSheet.data = await api('/plans/' + state.planId + '/cook-sheet');
  } catch (err) {
    cookSheet.error = err.message;
  }
  cookSheet.busy = false;
  render();
}

function wireCookSheet() {
  const open = $('cookOpen');
  if (open) open.addEventListener('click', () => {
    cookSheet.show = !cookSheet.show;
    if (cookSheet.show && !cookSheet.data) { loadCookSheet(); return; }
    render();
  });
  const refresh = $('cookRefresh');
  if (refresh) refresh.addEventListener('click', loadCookSheet);
}


function autoPanel() {
  const g = goals();
  return `<div class="card auto-card">
    <div class="row" style="align-items:baseline">
      <div style="flex:1;min-width:0">
        <h2 style="margin:0">Plan the week for me</h2>
        <p class="sub" style="margin:4px 0 0">Set the day's numbers and it fills
          seven days against them, cooking whatever your library is short of.</p>
      </div>
    </div>
    <div class="grid g2" style="margin-top:12px">
      <div><label for="aKcal">Calories a day, at most</label>
        <input id="aKcal" type="number" value="${Math.round(g.ceiling)}" min="800" max="6000" step="50"></div>
      <div><label for="aProt">Protein a day, at least (g)</label>
        <input id="aProt" type="number" value="${Math.round(g.floorP)}" min="20" max="400" step="5"></div>
      <div><label for="aFibre">Fibre a day, at least (g)</label>
        <input id="aFibre" type="number" value="${Math.round(g.floorF)}" min="5" max="100" step="1"></div>
      <div><label for="aMeals">Meals a day</label>
        <input id="aMeals" type="number" value="3" min="1" max="6"></div>
      <div><label for="aRepeat" title="How many days a dish can repeat. Lower means more variety and more cooking on Sunday; higher means fewer dishes and a shorter one.">Same dish, at most</label>
        <input id="aRepeat" type="number" value="5" min="1" max="14"></div>
      <div><label for="aBudget">Week's shopping, at most ($)</label>
        <input id="aBudget" type="number" value="120" min="20" max="2000" step="10"></div>
      <div><label for="aMinutes">Sunday, at most (minutes)</label>
        <input id="aMinutes" type="number" placeholder="no limit" min="20" max="600" step="10"></div>
      <div><label for="aCuisine">Theme for anything new</label>
        <select id="aCuisine">${(state.cuisines || [{ id: 'any', label: 'No theme' }])
          .map((c) => `<option value="${esc(c.id)}">${esc(c.label)}</option>`).join('')}
        </select></div>
      <div><label for="aDiet">Diet</label>
        <select id="aDiet">${optionsFor(DIETS, 'any')}</select></div>
      <div><label for="aEven">The day</label>
        <select id="aEven">
          <option value=""${goal.even ? '' : ' selected'}>Breakfast smaller than dinner</option>
          <option value="1"${goal.even ? ' selected' : ''}>Every meal the same size</option>
        </select></div>
    </div>
    <div class="row" style="margin-top:14px">
      <button id="aGo" class="primary" ${auto.busy ? 'disabled' : ''}>${
        auto.busy ? 'Planning…' : 'Plan my week'}</button>
      <span class="muted small">This replaces the week. Undo is on the Data tab.</span>
    </div>
    <div id="aOut" style="margin-top:14px">${auto.result ? autoSummary(auto.result) : ''}</div>
  </div>`;
}

function autoSummary(res) {
  const days = res.days || [];
  if (!days.length) {
    return `<div class="warn">${esc(res.message || 'Nothing could be planned.')}</div>`;
  }
  const rows = days.map((d, i) => {
    const t = d.totals || {};
    const met = d.met || {};
    const missed = [
      met.kcal ? '' : 'over on calories',
      met.protein ? '' : 'short on protein',
      met.fibre ? '' : 'short on fibre',
    ].filter(Boolean);
    return `<div class="auto-day${missed.length ? ' miss' : ''}">
      <div class="auto-day-top">
        <b>${esc(DAYS[i % 7])}</b>
        <span class="num small">${Math.round(t.kcal || 0)} kcal &middot;
          ${Math.round(t.p || 0)}g protein &middot; ${Math.round(t.fb || 0)}g fibre</span>
      </div>
      <div class="muted small">${esc((d.names || []).join(' · '))}</div>
      ${missed.length ? `<div class="small warn-text">${esc(missed.join(', '))}</div>` : ''}
    </div>`;
  }).join('');

  const cookNote = res.cookMinutes != null ? (() => {
    const h = Math.floor(res.cookMinutes / 60);
    const m = res.cookMinutes % 60;
    const clock = h ? `${h}h ${m}m` : `${m} min`;
    return `<div class="spend-row"><span>Sunday, start to finish</span>
      <b class="num">${clock}</b></div>`;
  })() : '';

  const spend = (res.estimatedCost != null || cookNote) ? `<div class="spend">
      ${cookNote}
      ${res.estimatedCost != null ? `<div class="spend-row">
        <span>At the till</span><b class="num">${money(res.estimatedCost)}</b></div>
      <div class="spend-row">
        <span>Eaten this week</span><b class="num">${money(res.eatenCost)}</b></div>
      <div class="spend-row muted">
        <span>Pack you keep</span><span class="num">${money(res.leftOverCost)}</span></div>
      ${(res.mostlyLeftOver || []).length ? `<div class="muted small"
        style="margin-top:8px">Mostly left over: ${res.mostlyLeftOver.map((x) =>
          `${esc(shortFood(x.food))} ${money(x.spend)} (${x.usedPercent}% used)`)
          .join(' &middot; ')}</div>` : ''}` : ''}
    </div>` : '';

  return `<div class="row" style="align-items:baseline;margin-bottom:6px">
      <h4 style="margin:0;flex:1">What it planned</h4>
      <button class="ghost tiny" id="aDismiss">Hide this</button></div>
    <p class="note">${esc(res.message || '')}</p>
    ${spend}
    ${res.budget && res.eatenCost && res.eatenCost > res.budget
      && !res.cheaperRoundAdded ? `<div class="warn" style="margin-top:10px">
      Your saved recipes are what makes this expensive -- the planner can only
      choose from them, and cheaper ones it composed did not hold the targets.
      Deleting the dearer recipes and planning again lets it build to the
      budget from scratch.</div>` : ''}
    ${res.fewerDishesForTime ? `<div class="note" style="margin-top:10px">
      Leaned on repeats rather than variety to fit the time you gave Sunday.</div>` : ''}
    <div class="auto-days">${rows}</div>`;
}

function wireAuto() {
  const open = $('autoOpen');
  if (open) {
    open.textContent = auto.show ? 'Hide the planner' : 'Plan it for me';
    open.addEventListener('click', () => { auto.show = !auto.show; render(); });
  }
  const dismiss = $('aDismiss');
  if (dismiss) dismiss.addEventListener('click', () => {
    auto.result = null;
    render();
  });
  const go = $('aGo');
  if (!go) return;
  go.addEventListener('click', async () => {
    // Read every field before the next line touches the DOM. `render()`
    // rebuilds this form from scratch, and every field below except the
    // three reading live goals() falls back to its hardcoded default the
    // instant that happens -- so a budget or a repeat count typed in was
    // being silently discarded and the server-side default sent instead.
    const body = {
      days: 7,
      meals_per_day: Number($('aMeals').value) || 3,
      ceiling: Number($('aKcal').value) || 2000,
      floor_protein: Number($('aProt').value) || 150,
      floor_fibre: Number($('aFibre').value) || 25,
      max_repeats: Number($('aRepeat').value) || 3,
      cuisine: ($('aCuisine') || {}).value || 'any',
      diet: ($('aDiet') || {}).value || 'any',
      budget: Number($('aBudget').value) || null,
      max_sunday_minutes: Number(($('aMinutes') || {}).value) || null,
      even_meals: !!($('aEven') || {}).value,
      apply: true,
    };
    auto.busy = true;
    render();
    try {
      auto.result = await api('/plans/' + state.planId + '/autoplan',
        { method: 'POST', body });
      // The planner may have composed dishes and it writes the day's targets
      // into the plan, so both have moved underneath us.
      await loadRecipes();
      await loadPlan();
    } catch (err) {
      toast(err.message);
    }
    auto.busy = false;
    render();
  });
}

/* -------------------------------------------------------- write your own */

const own = { name: '', servings: 4, meal: '', items: [], steps: [''], busy: false };

function ownMacros() {
  const t = { kcal: 0, p: 0, c: 0, f: 0, fb: 0 };
  own.items.forEach((i) => {
    if (!i.per100 || !i.grams) return;
    const factor = i.grams / 100;
    ['kcal', 'p', 'c', 'f', 'fb'].forEach((k) => {
      t[k] += (i.per100[k] || 0) * factor;
    });
  });
  const per = Math.max(1, own.servings);
  return {
    total: t,
    perServing: Object.fromEntries(
      Object.entries(t).map(([k, v]) => [k, v / per])),
  };
}

// Where a line's figures came from. An estimate is honest and useful; silence
// is not, and silence is what produced a recipe reading 0 kcal.
function nutritionSource(item) {
  if (!item.per100) {
    return `<span class="tag stop">no nutrition</span>
      <span class="muted small">Enter it by hand, or this adds nothing to
        the totals.</span>`;
  }
  if (item.per100From === 'estimate') {
    return `<span class="tag">estimated</span>
      <span class="muted small">from ${esc(item.per100Name || 'a similar food')}</span>`;
  }
  if (item.per100From === 'typed') return '<span class="tag">entered by hand</span>';
  return '<span class="tag ok">from the label</span>';
}


function ownCost() {
  // Only counts lines with a known price, and says how many it could not.
  let cost = 0;
  let priced = 0;
  own.items.forEach((i) => {
    if (i.perKg && i.grams) { cost += i.perKg * (i.grams / 1000); priced += 1; }
  });
  return { cost, priced, missing: own.items.length - priced };
}

function viewOwn() {
  const m = ownMacros();
  const c = ownCost();
  const per = m.perServing;

  const rows = own.items.map((i, idx) => `<tr>
    <td><div class="prod-row">${thumb({ image: i.image, name: i.food })}
      <div style="min-width:0"><b>${esc(i.food)}</b>
        <div class="muted small">${esc(i.matched || 'no product matched')}</div>
        ${nutritionSource(i)}</div></div></td>
    <td class="r" data-label="Grams">
      <input type="number" class="mult" style="width:74px" data-grams="${idx}"
        value="${i.grams}" min="1" max="20000"> g</td>
    <td class="r num" data-label="Energy">${i.per100
      ? Math.round((i.per100.kcal || 0) * i.grams / 100) + ' kcal'
      : '<span class="muted small">not known</span>'}</td>
    <td class="r num" data-label="Protein">${i.per100
      ? Math.round((i.per100.p || 0) * i.grams / 100) + ' g'
      : '<span class="muted small">&mdash;</span>'}</td>
    <td class="r num" data-label="Cost">${i.perKg
      ? money(i.perKg * i.grams / 1000) : '&mdash;'}</td>
    <td class="r"><button class="ghost tiny" data-rmitem="${idx}"
      title="Remove">&times;</button></td>
  </tr>`).join('');

  const unknown = own.items.filter((i) => !i.per100).length;

  return `<div class="card">
    <h2>Write your own recipe</h2>
    <p class="sub">Search a product to add it. Figures come from the label
      where the store has one, and from the ingredient table where it does
      not.</p>
    ${unknown ? `<div class="warn">${unknown} ingredient${
      unknown === 1 ? ' has' : 's have'} no nutrition, so ${
      unknown === 1 ? 'it is' : 'they are'} missing from the totals below.
      Add the figures by hand to include ${unknown === 1 ? 'it' : 'them'}.</div>`
      : ''}

    <div class="grid g2">
      <div><label for="ownName">Name</label>
        <input id="ownName" value="${esc(own.name)}" placeholder="e.g. Sunday chilli"></div>
      <div><label for="ownServ">Makes how many servings</label>
        <input id="ownServ" type="number" min="1" max="20" value="${own.servings}"></div>
    </div>
    <div class="grid g2" style="margin-top:10px">
      <div><label for="ownMeal">Meal</label>
        <select id="ownMeal">${optionsFor(MEALS, own.meal)}</select></div>
    </div>

    <h4 style="margin:18px 0 6px">Ingredients</h4>
    <div class="row">
      <input id="ownSearch" placeholder="Search a product to add&hellip;"
        style="flex:1;min-width:170px">
      <button id="ownFind" class="primary">Search</button>
      ${scannerSupported() ? '<button id="ownScan">Scan</button>' : ''}
    </div>
    <div id="ownResults" style="margin-top:10px"></div>

    ${own.items.length ? `<div class="scroll" style="margin-top:12px"><table>
      <thead><tr><th>Ingredient</th><th class="r">Amount</th>
        <th class="r">Energy</th><th class="r">Protein</th>
        <th class="r">Cost</th><th></th></tr></thead>
      <tbody>${rows}</tbody></table></div>

      <div class="stats" style="margin-top:14px">
        <div class="stat"><div class="k">Per serving</div>
          <div class="v">${Math.round(per.kcal)}<span class="muted"
            style="font-size:14px"> kcal</span></div></div>
        <div class="stat"><div class="k">Protein each</div>
          <div class="v">${Math.round(per.p)}<span class="muted"
            style="font-size:14px"> g</span></div></div>
        <div class="stat"><div class="k">Fibre each</div>
          <div class="v">${Math.round(per.fb)}<span class="muted"
            style="font-size:14px"> g</span></div></div>
        <div class="stat"><div class="k">Cost each</div>
          <div class="v">${c.priced ? money(c.cost / Math.max(1, own.servings)) : '—'}</div></div>
      </div>
      ${c.missing ? `<p class="muted small" style="margin:0">${c.missing}
        ingredient${c.missing === 1 ? ' has' : 's have'} no price, so the cost is
        a floor rather than a total.</p>` : ''}
      <div class="macros num" style="margin-top:10px">
        <span><b>${Math.round(per.c)}</b>g carb</span>
        <span><b>${Math.round(per.f)}</b>g fat</span>
        <span class="muted">per serving &middot; whole recipe
          ${Math.round(m.total.kcal)} kcal</span></div>`
      : '<p class="muted small" style="margin-top:10px">No ingredients yet.</p>'}

    <h4 style="margin:20px 0 6px">Method</h4>
    ${own.steps.map((st, i) => `<div class="row" style="margin-bottom:6px">
      <span class="muted num small" style="width:20px">${i + 1}.</span>
      <input data-step="${i}" value="${esc(st)}" placeholder="What happens at this step"
        style="flex:1">
      <button class="ghost tiny" data-rmstep="${i}" title="Remove">&times;</button>
    </div>`).join('')}
    <button id="ownAddStep" class="tiny">Add a step</button>

    <div class="row" style="margin-top:18px">
      <button id="ownSave" class="primary"${own.items.length ? '' : ' disabled'}>
        Save to my library</button>
      <button id="ownClear" class="ghost">Start again</button>
    </div>
    <div id="ownOut" style="margin-top:12px"></div>
  </div>`;
}

async function ownSearch() {
  const q = ($('ownSearch').value || '').trim();
  if (!q) return;
  const out = $('ownResults');
  out.innerHTML = '<div class="note">Searching&hellip;</div>';
  try {
    // The catalogue first: instant, and it carries nutrition where a barcode
    // scan has previously filled it in.
    let res = await api('/catalogue?limit=8&q=' + encodeURIComponent(q));
    let items = res.products || [];
    if (!items.length) {
      const live = await api('/search?limit=8&q=' + encodeURIComponent(q));
      items = live.products || [];
    }
    if (!items.length) {
      out.innerHTML = `<div class="note">Nothing found. You can still add it
        by hand below.</div>${ownManualHtml(q)}`;
      wireOwnManual();
      return;
    }
    ownFound = items;
    out.innerHTML = `<div class="scroll"><table><tbody>${items.map((p, i) => `
      <tr><td><div class="prod-row">${thumb(p)}<div style="min-width:0">
        <b>${esc(p.name)}</b>
        <div class="muted small">${esc(p.package_size || '')}
          ${p.per_kg ? '&middot; ' + money(p.per_kg) + '/kg' : ''}</div></div></div></td>
      <td class="r"><button class="tiny" data-pick-ing="${i}">Add</button></td></tr>`
    ).join('')}</tbody></table></div>${ownManualHtml(q)}`;
    wireOwnPick();
    wireOwnManual();
  } catch (err) {
    out.innerHTML = `<div class="err">${esc(err.message)}</div>`;
  }
}

let ownFound = [];

function ownManualHtml(q) {
  return `<details style="margin-top:10px"><summary class="muted small">
      Add "${esc(q)}" by hand instead</summary>
    <div class="row" style="margin-top:8px">
      <input id="ownManualName" value="${esc(q)}" placeholder="Name" style="flex:1">
      <button id="ownManualAdd" class="tiny">Add</button>
    </div>
    <div class="row" style="margin-top:8px">
      <input id="ownManualKcal" type="number" placeholder="kcal/100g" style="flex:1;min-width:92px">
      <input id="ownManualP" type="number" placeholder="protein" style="flex:1;min-width:80px">
      <input id="ownManualC" type="number" placeholder="carbs" style="flex:1;min-width:74px">
      <input id="ownManualF" type="number" placeholder="fat" style="flex:1;min-width:66px">
      <input id="ownManualFb" type="number" placeholder="fibre" style="flex:1;min-width:74px">
    </div>
    <p class="muted small" style="margin:6px 0 0">All per 100g. Leave them
      blank and it will estimate from a similar food.</p>
    </details>`;
}

function wireOwnManual() {
  const add = $('ownManualAdd');
  if (!add) return;
  add.addEventListener('click', async () => {
    const name = ($('ownManualName').value || '').trim();
    if (!name) return;
    const typed = {
      kcal: Number($('ownManualKcal').value) || 0,
      p: Number($('ownManualP').value) || 0,
      c: Number(($('ownManualC') || {}).value) || 0,
      f: Number(($('ownManualF') || {}).value) || 0,
      fb: Number(($('ownManualFb') || {}).value) || 0,
    };
    // Nothing typed at all is a request for a guess, not a request for zero.
    const blank = !Object.values(typed).some((v) => v);
    const found = blank ? await nutritionFor({ name }) : null;
    own.items.push({
      food: name, grams: 100, image: '', matched: 'entered by hand',
      per100: blank ? found.per100 : typed,
      per100From: blank ? found.from : 'typed',
      per100Name: blank ? found.name : '',
      perKg: null, store: '', stockcode: '',
    });
    render();
  });
}

// Store listings carry no nutrition panel. Open Food Facts has one but only
// answers to a barcode, and often has never seen an Australian store line --
// which is how a written-your-own recipe ended up in the week reading 0 kcal.
// Fall back to the ingredient table, which knows what chicken breast is
// whether or not anyone has scanned that particular packet.
async function nutritionFor(product) {
  if (product.barcode) {
    try {
      const res = await api('/barcode/' + encodeURIComponent(product.barcode));
      const n = res.nutrition && res.nutrition.nutrition;
      if (n && n.kcal != null) {
        return { per100: n, from: 'label', name: '' };
      }
    } catch (_) { /* fall through to the estimate */ }
  }
  try {
    const res = await api('/nutrition/estimate?name='
      + encodeURIComponent(product.name || ''));
    if (res.status === 'ok') {
      return { per100: res.per100, from: 'estimate', name: res.matched };
    }
  } catch (_) { /* nothing known, and the row will say so */ }
  return { per100: null, from: 'none', name: '' };
}


function wireOwnPick() {
  document.querySelectorAll('[data-pick-ing]').forEach((b) => {
    b.addEventListener('click', async () => {
      const p = ownFound[Number(b.dataset.pickIng)];
      if (!p) return;
      b.disabled = true;
      b.textContent = 'Adding…';
      const found = await nutritionFor(p);
      own.items.push({
        food: p.name, grams: p.pack_g || 100, image: p.image || '',
        matched: p.package_size || '',
        per100: found.per100, per100From: found.from, per100Name: found.name,
        perKg: p.per_kg || null, store: p.store || '',
        stockcode: String(p.stockcode || ''),
      });
      render();
    });
  });
}

function wireOwn() {
  const name = $('ownName');
  if (name) name.addEventListener('input', () => { own.name = name.value; });
  const serv = $('ownServ');
  if (serv) serv.addEventListener('change', () => {
    own.servings = Math.max(1, Number(serv.value) || 1);
    render();
  });
  const meal = $('ownMeal');
  if (meal) meal.addEventListener('change', () => { own.meal = meal.value; });

  const find = $('ownFind');
  if (find) find.addEventListener('click', ownSearch);
  const search = $('ownSearch');
  if (search) search.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') ownSearch();
  });
  const scanBtn = $('ownScan');
  if (scanBtn) scanBtn.addEventListener('click', openScanner);

  document.querySelectorAll('[data-grams]').forEach((input) => {
    input.addEventListener('change', () => {
      own.items[Number(input.dataset.grams)].grams =
        Math.max(1, Number(input.value) || 1);
      render();
    });
  });
  document.querySelectorAll('[data-rmitem]').forEach((b) => {
    b.addEventListener('click', () => {
      own.items.splice(Number(b.dataset.rmitem), 1);
      render();
    });
  });
  document.querySelectorAll('[data-step]').forEach((input) => {
    input.addEventListener('input', () => {
      own.steps[Number(input.dataset.step)] = input.value;
    });
  });
  document.querySelectorAll('[data-rmstep]').forEach((b) => {
    b.addEventListener('click', () => {
      own.steps.splice(Number(b.dataset.rmstep), 1);
      if (!own.steps.length) own.steps = [''];
      render();
    });
  });
  const addStep = $('ownAddStep');
  if (addStep) addStep.addEventListener('click', () => {
    own.steps.push('');
    render();
  });

  const clear = $('ownClear');
  if (clear) clear.addEventListener('click', () => {
    if (!window.confirm('Discard this recipe?')) return;
    own.name = ''; own.servings = 4; own.items = []; own.steps = [''];
    render();
  });

  const save = $('ownSave');
  if (save) {
    save.addEventListener('click', async () => {
      const title = (own.name || '').trim();
      if (!title) {
        $('ownOut').innerHTML = '<div class="err">Give it a name first.</div>';
        return;
      }
      save.disabled = true;
      save.textContent = 'Saving…';
      const m = ownMacros();
      try {
        const res = await api('/recipes/save-many', {
          method: 'POST',
          body: {
            recipes: [{
              name: title,
              servings: own.servings,
              perServing: {
                kcal: Math.round(m.perServing.kcal),
                p: Math.round(m.perServing.p * 10) / 10,
                c: Math.round(m.perServing.c * 10) / 10,
                f: Math.round(m.perServing.f * 10) / 10,
                fb: Math.round(m.perServing.fb * 10) / 10,
              },
              ingredients: own.items.map((i) => ({
                food: i.food,
                gramsPerServing: Math.round(i.grams / own.servings),
                gramsTotal: i.grams,
                query: i.food,
                pack: null,
                aisle: guessAisle(i.food),
                role: 'other',
                // Without these the saved recipe had no picture -- the photo
                // map only knows the builder's own ingredient names, and a
                // store product is not one of them -- and no way to be
                // recalculated later.
                image: i.image || '',
                per100: i.per100 || null,
              })),
              steps: own.steps.filter((x) => x.trim()),
              storage: '',
              reheat: [],
              ownRecipe: true,
              meal: own.meal || undefined,
            }],
          },
        });
        await loadRecipes();
        $('ownOut').innerHTML = res.saved
          ? `<div class="note">Saved. It is in <b>Recipes</b>, and can be put
             on a day under <b>Week</b>.</div>`
          : '<div class="warn">A recipe with that name is already saved.</div>';
        save.textContent = 'Save to my library';
        save.disabled = false;
      } catch (err) {
        $('ownOut').innerHTML = `<div class="err">${esc(err.message)}</div>`;
        save.textContent = 'Save to my library';
        save.disabled = false;
      }
    });
  }
}

/* ------------------------------------------------------------------- boot */

async function boot() {
  try {
    authConfig = await api('/auth/config');
  } catch (_) { /* fall back to the defaults above */ }

  // A reset link lands on /?reset=<token> and has to be answered before
  // anything else: the person following it cannot sign in, which is the whole
  // reason they are here. Nothing checked for it, so every reset email led to
  // the sign-in form and the reset screen was unreachable -- the form existed,
  // the endpoint worked, and there was no way to get from one to the other.
  if (pendingResetToken()) {
    showReset();
    return;
  }

  const who = await api('/auth/me');
  if (!who.signedIn) { showAuth(); return; }
  state.user = who;
  $('whoami').textContent = who.email;
  $('userBox').classList.remove('hide');
  $('authView').classList.add('hide');
  $('appView').classList.remove('hide');

  await loadPlans();
  if (!state.plans.length) {
    const created = await api('/plans', { method: 'POST',
      body: { name: 'My plan', data: emptyPlan() } });
    state.planId = created.id;
    await loadPlans();
  }
  await loadPlan();
  await loadRecipes();
  loadFoodImages();      // deliberately not awaited -- the page is usable now
  loadGoals();
  api('/auto-price').then((a) => { state.autoPrice = a; }).catch(() => {});
  try {
    state.cuisines = (await api('/cuisines')).cuisines;
  } catch (_) { state.cuisines = null; }
  render();
}

boot().catch((err) => {
  console.error(err);
  showAuth();
});
