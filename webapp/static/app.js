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
    throw new Error(typeof detail === 'string' ? detail : 'Request failed (' + res.status + ')');
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
  await api('/plans/' + state.planId, { method: 'PUT', body: { data: state.plan.data } });
}

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
                  recipes: viewRecipes, data: viewData };
  host.innerHTML = (views[state.tab] || viewWeek)();
  if (state.tab === 'search') wireSearch();
  if (state.tab === 'shop') wireShop();
  if (state.tab === 'data') wireData();
  if (state.tab === 'build') wireBuild();
  if (state.tab === 'week') wireWeek();
  if (state.tab === 'recipes') wireRecipes();
  if (state.tab === 'findrec') wireFindRecipe();
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
      <div><label for="bCuisine">Theme</label><select id="bCuisine">
        ${(state.cuisines || [{ id: 'any', label: 'No theme' }]).map((c) =>
          `<option value="${esc(c.id)}">${esc(c.label)}</option>`).join('')}
      </select></div>
      <div><label for="bDiet">Diet</label><select id="bDiet">
        <option value="any">No restriction</option>
        <option value="pescatarian">Pescatarian</option>
        <option value="vegetarian">Vegetarian</option>
        <option value="vegan">Vegan</option></select></div>
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
      <b>Offer me choices</b> proposes a few different meals so you can pick.</p>
    <div id="bOut" style="margin-top:16px"></div></div>`;
}

function wireBuild() {
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
        kcal_per_serving: Number($('bKcal').value),
        protein_per_serving: Number($('bProt').value),
        diet: $('bDiet').value,
        cuisine: ($('bCuisine') || {}).value || 'any',
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
    return `<div class="meal">${esc(i.food || i.name || '')}
      <span class="num">${esc(per)}</span>${tot}</div>`;
  }).join('');

  const steps = (r.steps || []).length
    ? `<h4>Method</h4><ol class="steps">${
        r.steps.map((st) => `<li>${esc(st)}</li>`).join('')}</ol>` : '';

  const reheat = (r.reheat || []).length
    ? `<h4>Storing and reheating</h4>
       ${r.storage ? `<p class="muted small">${esc(r.storage)}</p>` : ''}
       <ul class="steps">${r.reheat.map((t) => `<li>${esc(t)}</li>`).join('')}</ul>` : '';

  const notes = (r.notes || '').trim()
    ? `<p class="note small" style="margin-top:10px">${esc(r.notes)}</p>` : '';

  const controls = o.library ? `<div class="row" style="margin-top:12px">
      <div class="rating">${stars(r.id, r.rating)}</div>
      <div style="flex:1"></div>
      <span class="counter" title="How many times you have made this. Recipes cooked twice or more show under Favourites when planning a week.">
        <button class="ghost tiny" data-cooked="${r.id}" data-step="-1"
          ${r.timesCooked ? '' : 'disabled'} aria-label="One fewer">&minus;</button>
        <span class="num">cooked ${r.timesCooked || 0}&times;</span>
        <button class="ghost tiny" data-cooked="${r.id}" data-step="1"
          aria-label="One more">+</button>
      </span>
      <button class="ghost tiny danger" data-del="${r.id}">Delete</button>
    </div>` : '';

  const add = o.pickable
    ? `<button class="tiny" data-add="${r.id}">Add to a day</button>` : '';

  const cat = CAT_ORDER.includes(r.category) ? r.category : 'other';
  return `<div class="day recipe">
    <div class="row"><span class="dot cat-${esc(cat)}"
      title="${esc(CAT_LABEL[cat])}"></span>
      <h3 style="flex:1">${esc(r.name)}</h3>${add}</div>
    ${r.cuisineLabel && r.cuisine !== 'any'
      ? `<span class="tag">${esc(r.cuisineLabel)}</span>` : ''}
    ${r.source ? `<a class="tag" href="${esc(r.source)}" target="_blank"
      rel="noopener noreferrer">from ${esc(r.sourceName || 'the web')}</a>` : ''}
    ${macroLine(r.perServing, r.servings)}
    ${ing}${steps}${reheat}${notes}${controls}</div>`;
}

function viewRecipes() {
  const list = state.recipes || [];
  if (!list.length) {
    return `<div class="card"><h2>No saved recipes</h2>
      <p class="sub">Build some in the Recipe builder, then choose
        &ldquo;Save to library&rdquo;. Rated recipes sort to the top here.</p></div>`;
  }
  const rated = list.filter((r) => r.rating).length;
  return `<div class="card">
    <h2>Recipe library</h2>
    <p class="sub">${list.length} saved, ${rated} rated. Best first.</p>
    <div class="grid g2">${list.map((r) => recipeCard(r, { library: true })).join('')}</div>
  </div>`;
}

function wireRecipes() {
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





/* -------------------------------------------------------- shopping list */

function gotSet() {
  const d = state.plan.data;
  if (!Array.isArray(d.got)) d.got = [];
  return new Set(d.got);
}

function viewShop() {
  const d = state.plan.data;
  const shop = d.shop || {};
  const entries = Object.entries(shop);
  if (!entries.length) {
    return `<div class="card"><h2>Nothing on the list</h2>
      <p class="sub">Plan a week, or build recipes, then come back.</p></div>`;
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

  let total = 0;
  let remaining = 0;
  const sections = order.concat(Object.keys(byAisle).filter((a) => !order.includes(a)))
    .filter((a) => byAisle[a])
    .map((aisle) => {
      const rows = byAisle[aisle].map(([food, meta]) => {
        const p = latestPrice(food);
        const packs = meta.packsNeeded || 1;
        const cost = p && p.price ? p.price * packs : null;
        if (cost) { total += cost; if (!got.has(food)) remaining += cost; }
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
              ${ticked ? 'checked' : ''}> <span>${esc(food)}</span></label>
            <div class="muted small">${meta.grams ? meta.grams + ' g' : ''}${
              packs > 1 ? ' &middot; ' + packs + ' packs' : ''}${
              p && p.matched ? ' &middot; ' + esc(p.matched) : ''}${link}</div>
            </div></div></td>
          <td class="r num">${p && p.pack ? p.pack + ' g' : '&mdash;'}</td>
          <td class="r num">${money(p && p.price)}
            <button class="ghost tiny" data-edit="${esc(food)}" title="Correct this price">edit</button></td>
          <td class="r num muted">${kg ? money(kg) + '/kg' : '&mdash;'}</td>
          <td class="r muted small">${esc((p && p.store) || '')}
            <button class="ghost tiny" data-drop="${esc(food)}" title="Remove from list">&times;</button></td>
        </tr>`;
      }).join('');
      return `<tr><td colspan="5" class="aisle">${esc(aisle)}</td></tr>` + rows;
    }).join('');

  return `<div class="card">
    <div class="row" style="margin-bottom:12px">
      <div style="flex:1"><h2>Shopping list</h2>
        <p class="sub" style="margin:0">${got.size} of ${entries.length} in the basket</p></div>
      <button id="refreshBtn" class="primary">Refresh prices</button>
      <button id="clearGot" class="ghost">Untick all</button>
    </div>
    <div class="stats">
      <div class="stat"><div class="k">Basket total</div><div class="v">${money(total)}</div></div>
      <div class="stat"><div class="k">Still to get</div><div class="v">${money(remaining)}</div></div>
      <div class="stat"><div class="k">Items</div><div class="v">${entries.length}</div></div>
    </div>
    <div id="refreshOut"></div>
    <div class="scroll"><table>
      <thead><tr><th>Item</th><th class="r">Pack</th><th class="r">Price</th>
        <th class="r">Per kg</th><th class="r">Store</th></tr></thead>
      <tbody>${sections}</tbody></table></div></div>`;
}

function wireShop() {
  document.querySelectorAll('[data-got]').forEach((box) => {
    box.addEventListener('change', async () => {
      const food = box.dataset.got;
      const got = gotSet();
      if (box.checked) got.add(food); else got.delete(food);
      state.plan.data.got = [...got];
      // Repaint the row immediately; the save follows without blocking it.
      const row = box.closest('tr');
      if (row) row.classList.toggle('got', box.checked);
      await savePlan();
      const head = document.querySelector('.card .sub');
      if (head) head.textContent =
        `${got.size} of ${Object.keys(state.plan.data.shop || {}).length} in the basket`;
    });
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
function dealVerdict(points) {
  if (!points || points.length < 2) {
    return { label: 'no history yet', cls: '', detail: 'Refresh again next week.' };
  }
  const now = points[points.length - 1].v;
  const prior = points.slice(0, -1).map((p) => p.v);
  const lo = Math.min(...prior);
  const hi = Math.max(...prior);
  const mean = prior.reduce((a, b) => a + b, 0) / prior.length;
  const delta = (now - mean) / mean * 100;

  if (now <= lo) {
    return { label: 'cheapest yet', cls: 'ok',
             detail: `Lowest of ${points.length} readings.` };
  }
  if (delta <= -8) {
    return { label: 'good week to buy', cls: 'ok',
             detail: `${Math.abs(delta).toFixed(0)}% below its usual ${money(mean)}/kg.` };
  }
  if (delta >= 8) {
    return { label: 'dearer than usual', cls: 'stop',
             detail: `${delta.toFixed(0)}% above its usual ${money(mean)}/kg.` };
  }
  if (now >= hi) {
    return { label: 'highest yet', cls: 'stop',
             detail: `Dearest of ${points.length} readings.` };
  }
  return { label: 'about normal', cls: '',
           detail: `Usual price is around ${money(mean)}/kg.` };
}

function viewPrices() {
  const prices = state.plan.data.prices || {};
  const entries = Object.entries(prices).filter(([, h]) => h && h.length);
  if (!entries.length) {
    return `<div class="card"><h2>No prices yet</h2>
      <p class="sub">Use &ldquo;Refresh prices&rdquo; on the shopping list.
        Each refresh adds a reading, and the trend appears once there are two.</p></div>`;
  }

  const rows = entries.map(([food, history]) => {
    const points = history
      .map((e) => ({ v: perKg(e), d: e.date }))
      .filter((p) => p.v);
    const now = points.length ? points[points.length - 1].v : null;
    const before = points.length > 1 ? points[points.length - 2].v : null;
    const verdict = dealVerdict(points);
    const last = history[history.length - 1];

    return `<tr>
      <td><b>${esc(food)}</b>
        <div class="muted small">${esc(last.matched || last.store || '')}
          ${last.source === 'manual' ? '<span class="tag">by hand</span>' : ''}</div></td>
      <td class="r num">${now ? money(now) + '/kg' : '&mdash;'}</td>
      ${deltaCell(now, before)}
      <td class="spark-cell">${sparkline(points)}</td>
      <td><span class="tag ${verdict.cls}">${verdict.label}</span>
        <div class="muted small">${verdict.detail}</div></td>
      <td class="r muted num small">${points.length}</td>
    </tr>`;
  }).join('');

  const good = entries.filter(([, h]) => {
    const pts = h.map((e) => ({ v: perKg(e) })).filter((p) => p.v);
    return ['cheapest yet', 'good week to buy'].includes(dealVerdict(pts).label);
  }).length;

  return `<div class="card">
    <h2>Prices over time</h2>
    <p class="sub">${entries.length} foods tracked${
      good ? `, <b>${good}</b> worth buying this week` : ''}.
      The dot on the line is the cheapest reading; the dark dot is now.</p>
    <div class="scroll"><table>
      <thead><tr><th>Food</th><th class="r">Now</th><th class="r">Change</th>
        <th>Trend</th><th>Verdict</th><th class="r">Readings</th></tr></thead>
      <tbody>${rows}</tbody></table></div></div>`;
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
    </div>

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
  // loading="lazy" matters: a catalogue page can hold sixty of these, and the
  // store CDNs are slow enough that eager loading stalls the whole table.
  if (!p.image) {
    return `<div class="thumb none" aria-hidden="true">${
      esc((p.name || '?').trim().charAt(0).toUpperCase())}</div>`;
  }
  return `<img class="thumb" src="${esc(p.image)}" alt="" loading="lazy"
    decoding="async" referrerpolicy="no-referrer"
    onerror="this.replaceWith(Object.assign(document.createElement('div'),
      {className:'thumb none',textContent:${JSON.stringify(
        (p.name || '?').trim().charAt(0).toUpperCase())}}))">`;
}

function resultRows(items, opts) {
  const showAge = opts && opts.showAge;
  return items.map((p, i) => {
    const key = `${p.store}:${p.stockcode}`;
    const link = p.url
      ? ` <a href="${esc(p.url)}" target="_blank" rel="noopener noreferrer" title="Open at the store">&#8599;</a>`
      : '';
    return `<tr>
      <td class="prod"><div class="prod-row">${thumb(p)}<div>
        <b>${esc(p.name)}</b>${p.on_special ? ' <span class="tag ok">special</span>' : ''}
        ${p.in_stock === false ? ' <span class="tag stop">out of stock</span>' : ''}${link}
        <div class="muted small">${esc(p.package_size || '')}${
          p.cup_string ? ' &middot; ' + esc(p.cup_string) : ''}</div></div></div></td>
      <td><span class="tag">${esc(p.store)}</span></td>
      <td class="r num">${p.pack_g ? p.pack_g + ' g' : '&mdash;'}</td>
      <td class="r num">${money(p.pack_price)}</td>
      <td class="r num">${p.per_kg ? money(p.per_kg) : '&mdash;'}</td>
      <td class="r"><button class="tiny" data-add-prod="${esc(key)}"
        data-idx="${i}">Add</button></td>
    </tr>`;
  }).join('');
}

function resultTable(items, note) {
  if (!items.length) {
    return `<div class="note">Nothing found. ${note || ''}</div>`;
  }
  return `${note ? `<div class="row" style="margin-bottom:10px">${note}</div>` : ''}
    <div class="scroll"><table><thead><tr>
      <th>Product</th><th>Store</th><th class="r">Pack</th>
      <th class="r">Price</th><th class="r">Per kg</th><th></th>
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
function guessAisle(name) {
  const n = (name || '').toLowerCase();
  if (/frozen|ice cream/.test(n)) return 'freezer';
  if (/chicken|beef|pork|lamb|mince|steak|sausage|bacon|salmon|tuna|prawn|fish/.test(n)) return 'meat';
  if (/milk|yoghurt|cheese|butter|cream|egg|tofu/.test(n)) return 'fridge';
  if (/apple|banana|orange|lemon|potato|carrot|onion|tomato|broccoli|spinach|lettuce|cucumber|avocado|berry|berries|grape|capsicum|zucchini|mushroom|pumpkin/.test(n)) return 'produce';
  return 'pantry';
}

function wireSearch() {
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

const DAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday',
              'Saturday', 'Sunday'];

const CAT_LABEL = { chicken: 'Chicken', beef: 'Beef', pork: 'Pork',
                    lamb: 'Lamb', fish: 'Fish & seafood',
                    vegetarian: 'Vegetarian', other: 'Other' };
const CAT_ORDER = ['chicken', 'beef', 'pork', 'lamb', 'fish', 'vegetarian', 'other'];

const week = { picker: null, monday: null };

function weekData() {
  const d = state.plan.data;
  if (!Array.isArray(d.week) || d.week.length !== 7) {
    d.week = DAYS.map((name) => ({ day: name, meals: [] }));
  }
  return d.week;
}

function recipeById(id) {
  return (state.recipes || []).find((r) => r.id === Number(id));
}

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

function viewWeek() {
  const data = weekData();
  const library = state.recipes || [];

  if (!library.length) {
    return `<div class="card"><h2>Plan your week</h2>
      <p class="sub">Your library is empty. Build recipes in the
        <b>Recipe builder</b> and save them, then plan days here.</p></div>`;
  }

  if (!week.monday) week.monday = mondayOf(new Date());
  const from = new Date(week.monday);
  const to = dayDate(6);

  let kcal = 0;
  let meals = 0;

  const cards = data.map((day, di) => {
    const date = dayDate(di);
    const rows = (day.meals || []).map((m, mi) => {
      const r = recipeById(m.recipeId);
      if (!r) return '';
      const per = r.perServing || {};
      kcal += (per.kcal || 0) * (m.servings || 1);
      meals += 1;
      return `<div class="meal row">
        <span class="dot cat-${esc(categoryOf(r))}" title="${esc(CAT_LABEL[categoryOf(r)])}"></span>
        <span style="flex:1;min-width:0">${esc(r.name)}</span>
        <span class="muted num">${Math.round(per.kcal || 0)}&times;${m.servings || 1}</span>
        <button class="ghost tiny" data-rm="${di}:${mi}" title="Remove">&times;</button>
      </div>`;
    }).join('');
    return `<div class="day${isToday(date) ? ' today' : ''}">
      <h3><span>${esc(day.day)}</span><span class="muted num">${shortDate(date)}</span></h3>
      ${rows || '<p class="muted small" style="margin:4px 0">Nothing planned.</p>'}
      <button class="tiny add-day" data-pick="${di}">+ Add a meal</button>
    </div>`;
  }).join('');

  return `<div class="card">
    <div class="row"><div style="flex:1">
      <h2>Plan your week</h2>
      <p class="sub" style="margin:0">${shortDate(from)} &ndash; ${shortDate(to)}
        &middot; ${meals} meal${meals === 1 ? '' : 's'}</p></div>
      <button id="weekPrev" class="ghost" title="Previous week">&larr;</button>
      <button id="weekToday" class="ghost">This week</button>
      <button id="weekNext" class="ghost" title="Next week">&rarr;</button>
    </div>
    <div class="row" style="margin-top:12px">
      <button id="weekShop" class="primary">Build shopping list</button>
      <button id="weekClear" class="ghost">Clear week</button>
    </div>
    <div class="stats" style="margin-top:14px">
      <div class="stat"><div class="k">Meals</div><div class="v">${meals}</div></div>
      <div class="stat"><div class="k">Total energy</div>
        <div class="v">${Math.round(kcal).toLocaleString()}</div></div>
      <div class="stat"><div class="k">Avg per meal</div>
        <div class="v">${meals ? Math.round(kcal / meals) : 0}</div></div>
    </div>
    <div id="weekOut"></div>
    <div class="calendar">${cards}</div></div>`;
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
        recipeId: Number(b.dataset.choose), servings,
      });
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

  document.querySelectorAll('[data-rm]').forEach((b) => {
    b.addEventListener('click', async () => {
      const [di, mi] = b.dataset.rm.split(':').map(Number);
      weekData()[di].meals.splice(mi, 1);
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

  const clear = $('weekClear');
  if (clear) {
    clear.addEventListener('click', async () => {
      if (!window.confirm('Clear every day of this week?')) return;
      state.plan.data.week = DAYS.map((name) => ({ day: name, meals: [] }));
      await savePlan();
      render();
    });
  }

  const build = $('weekShop');
  if (build) {
    build.addEventListener('click', async () => {
      const totals = {};
      weekData().forEach((day) => (day.meals || []).forEach((m) => {
        const r = recipeById(m.recipeId);
        if (!r) return;
        (r.ingredients || []).forEach((i) => {
          const line = totals[i.food] || (totals[i.food] = {
            aisle: i.aisle || 'pantry', woo: i.query || i.food,
            pack: i.pack || null, grams: 0, usedIn: [],
          });
          line.grams += (i.gramsPerServing || 0) * (m.servings || 1) * (r.servings || 1);
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
      await savePlan();
      $('weekOut').innerHTML = `<div class="note">Shopping list built:
        ${Object.keys(totals).length} items. Open the
        <b>Shopping list</b> tab to price and tick them off.</div>`;
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

const found = { recipe: null, servings: null, system: 'metric' };

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

function renderFound() {
  const r = found.recipe;
  const times = [
    r.prepTime ? `prep ${esc(r.prepTime)}` : '',
    r.cookTime ? `cook ${esc(r.cookTime)}` : '',
    r.totalTime ? `total ${esc(r.totalTime)}` : '',
  ].filter(Boolean).join(' · ');

  return `<div class="card" style="margin:0">
    <div class="row" style="align-items:flex-start">
      ${r.image ? `<img class="thumb" style="width:78px;height:78px"
        src="${esc(r.image)}" alt="" loading="lazy" referrerpolicy="no-referrer">` : ''}
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
      <div class="seg">
        <button class="${found.system === 'metric' ? 'on' : ''}" data-sys="metric">Metric</button>
        <button class="${found.system === 'imperial' ? 'on' : ''}" data-sys="imperial">Imperial</button>
      </div>
      <div style="flex:1"></div>
      <button id="impSave" class="primary tiny">Save to my library</button>
    </div>

    <h4 style="margin:16px 0 6px">Ingredients</h4>
    ${(r.lines || []).map((l) => `<div class="meal">${esc(l)}</div>`).join('')}

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
      save.disabled = true;
      save.textContent = 'Saving…';
      try {
        await api('/recipes/save-many', {
          method: 'POST',
          body: {
            recipes: [{
              name: r.name,
              servings: r.servings,
              ingredients: (r.lines || []).map((l) => ({ food: l, qty: '' })),
              steps: r.steps || [],
              storage: '',
              reheat: [],
              source: r.sourceUrl,
              sourceName: r.sourceName,
              imported: true,
              image: r.image || '',
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

/* ------------------------------------------------------------------- boot */

async function boot() {
  try {
    authConfig = await api('/auth/config');
  } catch (_) { /* fall back to the defaults above */ }
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
  try {
    state.cuisines = (await api('/cuisines')).cuisines;
  } catch (_) { state.cuisines = null; }
  render();
}

boot().catch((err) => {
  console.error(err);
  showAuth();
});
