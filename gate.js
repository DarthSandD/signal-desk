/* ══════════════════════════════════════════════════════════════════
   Signal Desk — access gate (accounts · social follow · payments)
   Drop-in module. If CONFIG is empty it falls back to the demo gate,
   so the site never breaks before Supabase is wired.
   ══════════════════════════════════════════════════════════════════ */
const GATE_CONFIG = {
  SUPABASE_URL: '',        // e.g. https://abcd.supabase.co
  SUPABASE_ANON_KEY: '',   // anon public key
  DISCORD_INVITE: 'https://discord.gg/your-invite',
  YOUTUBE_URL: 'https://youtube.com/@yourchannel',
  INSTAGRAM_URL: 'https://instagram.com/darren.lin_ai',
  PRICE_LABEL: '$9 / month',
};

const SignalGate = (() => {
  let sb = null, cfg = GATE_CONFIG;
  const configured = () => !!(cfg.SUPABASE_URL && cfg.SUPABASE_ANON_KEY);

  function el(html) {
    const d = document.createElement('div');
    d.innerHTML = html.trim();
    return d.firstElementChild;
  }

  async function loadSupabase() {
    if (sb) return sb;
    const { createClient } = await import('https://esm.sh/@supabase/supabase-js@2');
    sb = createClient(cfg.SUPABASE_URL, cfg.SUPABASE_ANON_KEY, {
      auth: { persistSession: true, autoRefreshToken: true },
    });
    return sb;
  }

  /* ── screens ─────────────────────────────────────────────────── */

  function screenAuth(mode = 'signin', msg = '') {
    const isUp = mode === 'signup';
    return el(`
      <div class="gate-card">
        <div class="brand"><span class="dot">⚡</span><span>Signal<em>Desk</em></span></div>
        <div class="gate-sub">🔒 ${isUp ? 'Create your account' : 'Members access — sign in'}</div>
        <form id="authForm">
          <label for="ae">Email</label>
          <input id="ae" type="email" autocomplete="email" placeholder="you@email.com" required>
          <label for="ap">Password</label>
          <input id="ap" type="password" autocomplete="${isUp ? 'new-password' : 'current-password'}" placeholder="••••••••" required minlength="6">
          <button class="gate-btn" type="submit">${isUp ? 'Create account →' : 'Sign in →'}</button>
        </form>
        <div class="gate-err" id="authErr">${msg}</div>
        <div class="gate-foot">
          ${isUp ? 'Already a member?' : 'New here?'}
          <a href="#" id="swapMode">${isUp ? 'Sign in' : 'Create a free account'}</a>
        </div>
      </div>`);
  }

  function screenFollow(needs) {
    const row = (key, label, icon, url, verified) => `
      <a class="follow-row ${verified ? 'ok' : ''}" href="${verified ? '#' : url}" target="_blank" data-p="${key}">
        <span class="fr-ico">${icon}</span>
        <span class="fr-txt"><b>${label}</b><small>${verified ? 'Verified ✓' : 'Follow, then verify'}</small></span>
        <span class="fr-act">${verified ? '✓' : 'Follow →'}</span>
      </a>`;
    return el(`
      <div class="gate-card wide">
        <div class="brand"><span class="dot">⚡</span><span>Signal<em>Desk</em></span></div>
        <div class="gate-sub">🎁 Free access — follow us on both to unlock</div>
        <div class="follow-list">
          ${row('discord', 'Discord', '💬', cfg.DISCORD_INVITE, !needs.discord)}
          ${row('youtube', 'YouTube', '▶️', cfg.YOUTUBE_URL, !needs.youtube)}
          ${row('instagram', 'Instagram', '📸', cfg.INSTAGRAM_URL, false)}
        </div>
        <div class="gate-note">Instagram is on the honour system — we can’t verify follows there.</div>
        <div class="gate-sep"><span>or</span></div>
        <button class="gate-btn" id="goPro">⭐ Go Pro — ${cfg.PRICE_LABEL}</button>
        <div class="gate-foot"><a href="#" id="signOut">Sign out</a></div>
      </div>`);
  }

  function screenPro(status) {
    const active = status?.sub_status === 'active';
    return el(`
      <div class="gate-card">
        <div class="brand"><span class="dot">⚡</span><span>Signal<em>Desk</em></span></div>
        <div class="gate-sub">⭐ ${active ? 'Pro is active' : 'Unlock every signal'}</div>
        <ul class="pro-list">
          <li>✓ All signals, all markets</li>
          <li>✓ Live-anchored levels on every timeframe</li>
          <li>✓ Instant alerts</li>
        </ul>
        <button class="gate-btn" id="goPro">${active ? 'Manage subscription' : 'Upgrade — ' + cfg.PRICE_LABEL}</button>
        <div class="gate-sep"><span>or</span></div>
        <button class="gate-btn ghost" id="goFree">Follow us for free access</button>
        <div class="gate-foot"><a href="#" id="signOut">Sign out</a></div>
      </div>`);
  }

  function mount(node, opts) {
    const gate = document.getElementById('gate');
    gate.innerHTML = '';
    gate.appendChild(node);
    gate.classList.remove('off');
    document.body.style.overflow = 'hidden';
    wire(node, opts);
  }

  function wire(node, opts) {
    const swap = node.querySelector('#swapMode');
    if (swap) swap.onclick = (e) => { e.preventDefault(); opts.mode = opts.mode === 'signup' ? 'signin' : 'signup'; opts.render(); };

    const form = node.querySelector('#authForm');
    if (form) form.onsubmit = async (e) => {
      e.preventDefault();
      const email = node.querySelector('#ae').value.trim();
      const pass = node.querySelector('#ap').value;
      const err = node.querySelector('#authErr');
      err.textContent = 'Working…';
      const client = await loadSupabase();
      const fn = opts.mode === 'signup' ? client.auth.signUp : client.auth.signInWithPassword;
      const { error } = await fn.call(client.auth, { email, password: pass });
      if (error) { err.textContent = error.message; return; }
      err.textContent = '';
      opts.onSignedIn?.();
    };

    node.querySelectorAll('.follow-row').forEach((a) => {
      a.onclick = async (e) => {
        if (a.classList.contains('ok')) { e.preventDefault(); return; }
        const p = a.dataset.p;
        if (p === 'instagram') { localStorage.setItem('sd.ig_claimed', '1'); return; } // honour system
        // real platforms: open OAuth in a popup, callback posts back the code
        e.preventDefault();
        const url = await oauthUrl(p);
        const w = window.open(url, 'oauth', 'width=520,height=680');
        window.__sdOauth = async (code) => { w?.close(); await finishOauth(p, code, opts); };
      };
    });

    const pro = node.querySelector('#goPro');
    if (pro) pro.onclick = async () => {
      const client = await loadSupabase();
      const { data, error } = await client.functions.invoke('stripe-checkout');
      if (error || !data?.url) { alert('Checkout unavailable: ' + (error?.message || 'no url')); return; }
      location.href = data.url;
    };
    const free = node.querySelector('#goFree');
    if (free) free.onclick = () => opts.render();

    const out = node.querySelector('#signOut');
    if (out) out.onclick = async (e) => { e.preventDefault(); (await loadSupabase()).auth.signOut(); location.reload(); };
  }

  async function oauthUrl(platform) {
    const redirect = `${cfg.SUPABASE_URL}/functions/v1/verify-social`;
    const client = await loadSupabase();
    if (platform === 'discord') {
      const p = new URLSearchParams({
        client_id: cfg.DISCORD_CLIENT_ID, redirect_uri: redirect,
        response_type: 'code', scope: 'identify guilds',
      });
      return `https://discord.com/oauth2/authorize?${p}`;
    }
    const p = new URLSearchParams({
      client_id: cfg.GOOGLE_CLIENT_ID, redirect_uri: redirect,
      response_type: 'code', scope: 'https://www.googleapis.com/auth/youtube.readonly',
      access_type: 'online', prompt: 'consent',
    });
    return `https://accounts.google.com/o/oauth2/v2/auth?${p}`;
  }

  async function finishOauth(platform, code, opts) {
    const client = await loadSupabase();
    const { data } = await client.functions.invoke('verify-social', { body: { platform, code } });
    if (data?.ok) { opts.render(); } else { alert(`${platform} not verified — follow us first, then retry.`); }
  }

  /* ── public ──────────────────────────────────────────────────── */

  async function init(opts = {}) {
    // Not configured → let the existing demo gate handle it.
    if (!configured()) return { demo: true };

    const client = await loadSupabase();
    const state = { mode: 'signin', render: null };

    const render = async () => {
      const { data: { session } } = await client.auth.getSession();
      if (!session) return mount(screenAuth(state.mode), { ...opts, ...state, render });

      const { data } = await client.functions.invoke('gate');
      if (data?.access) {
        document.getElementById('gate').classList.add('off');
        document.body.style.overflow = '';
        const chip = document.getElementById('hUserN');
        if (chip) chip.textContent = session.user.email?.split('@')[0] || 'member';
        return opts.onAccess?.(data.status);
      }
      const needs = data?.needs ?? { discord: true, youtube: true };
      if (needs.discord || needs.youtube) mount(screenFollow(needs), { ...opts, ...state, render });
      else mount(screenPro(data?.status), { ...opts, ...state, render });
    };

    state.render = render;
    client.auth.onAuthStateChange((_e, s) => { if (!s) render(); });
    await render();
    return { demo: false };
  }

  return { init, config: GATE_CONFIG };
})();

// expose to window so the page can call it (top-level const is module-scoped)
window.SignalGate = SignalGate;
